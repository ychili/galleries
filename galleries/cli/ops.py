"""Command-line operations"""

from __future__ import annotations

import argparse
import configparser
import contextlib
import csv
import functools
import logging
import os
import shutil
import stat
import sys
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, ParamSpec, TextIO, TypedDict, TypeVar

from .. import PROG, refresh, relatedtag, table_query, tagcount, util
from .lib import CollectionFinder, DBConfig, GlobalConfig, join_semicolon_list

if TYPE_CHECKING:
    from _typeshed import StrPath


P = ParamSpec("P")
ArgsT = TypeVar("ArgsT", bound=argparse.Namespace)
SettingsT = TypeVar("SettingsT")

log = logging.getLogger(PROG)


class _OpSettings(TypedDict):
    tag_fields: list[str]


class _ReadOpSettings(_OpSettings):
    input_file: Path | TextIO


class _ReadWriteOpSettings(_OpSettings):
    collection_root: Path
    path_field: str
    count_field: str


class InitSettings(TypedDict):
    root_dir: Path
    template_dir: Path | None
    path_finder: CollectionFinder
    bare: bool


class TraverseSettings(_ReadWriteOpSettings):
    output_file: Path | TextIO
    force: bool
    leaves_only: bool


class CountSettings(_ReadOpSettings):
    summarize: bool


class QuerySettings(_ReadOpSettings):
    term: list[str]
    sort_field: str | None
    reverse_sort: bool
    format: table_query.Format
    auto_format: table_query.Format
    field_formats: Path
    rich_table: Path


class RefreshSettings(_ReadWriteOpSettings):
    input_file: Path
    backup_suffix: str
    sort_spec: list[tuple[str, bool]]
    unique_fields: list[str]
    implicating_fields: set[str]
    no_check: bool
    validate: bool
    implications: list[Path]
    aliases: list[Path]
    removals: list[Path]
    tag_actions: list[Path]


class RelatedSettings(_ReadOpSettings):
    limit_results: int | None
    sort_metric: str
    term: list[str]


class _CLIError(Exception):
    """Some kind of fatal error"""

    def __init__(self, status: int = 1) -> None:
        super().__init__(status)
        self.status = status


def _sc_runner(sc_func: Callable[P, int]) -> Callable[P, int]:
    """Run sub-command function, handling exceptions."""

    @functools.wraps(sc_func)
    def run(*args: P.args, **kwargs: P.kwargs) -> int:
        try:
            return sc_func(*args, **kwargs)
        except _CLIError as err:
            return err.status
        except configparser.Error as err:
            log.debug(
                "A configparser.Error is causing %r to exit with error: %s",
                sc_func,
                err,
            )
            return 1

    return run


def path_sc(cla: argparse.Namespace, config: GlobalConfig) -> int:
    """Path sub-command"""
    collection = config.get_collections().find_collection(cla.collection)
    print(collection.collection)
    return 0


def init_sc(cla: argparse.Namespace, global_config: GlobalConfig) -> int:
    """Init sub-command"""
    root = Path(cla.directory or cla.collection or Path.cwd())
    maybe_template_dir = cla.template or (
        global_config.options["init"].get("TemplateDir")
    )
    template_dir = Path(maybe_template_dir) if maybe_template_dir else None
    settings = InitSettings(
        root_dir=root,
        template_dir=template_dir,
        path_finder=global_config.get_collections(),
        bare=cla.bare,
    )
    return init_op(settings)


def init_op(settings: InitSettings) -> int:
    """Init operation"""
    err_msg = "Unable to init"
    root = settings["root_dir"]
    if not root.is_dir():
        try:
            root.mkdir(parents=True, exist_ok=False)
        except OSError as err:
            log.error("%s: Failed to create root directory: %s", err_msg, err)
            return 1
        log.info("Created root directory: %s", root)
    paths = settings["path_finder"].find_collection(str(root))
    if paths.config.exists():
        log.error(
            "%s: Refusing to overwrite existing configuration file: %s",
            err_msg,
            paths.config,
        )
        return 1
    if settings["bare"]:
        paths.subdir.mkdir(exist_ok=True)
        paths.config.touch(exist_ok=False)
        log.info("Created empty configuration file: %s", paths.config)
        return 0
    if template_dir := settings["template_dir"]:
        template_dir = Path(template_dir).expanduser()
        if not template_dir.is_dir():
            log.error("%s: TemplateDir is not a directory: %s", err_msg, template_dir)
            return 1
        ignore = ignore_patterns(".*")
        try:
            shutil.copytree(
                template_dir, paths.subdir, ignore=ignore, copy_function=shutil.copy
            )
        except shutil.Error as err:
            log.error(
                "While copying files from TemplateDir '%s' to '%s':",
                template_dir,
                paths.subdir,
            )
            for src, dst, why in err.args[0]:
                log.error("Copying file '%s' to '%s': %s", src, dst, why)
            return 1
        except FileExistsError as err:
            log.error("%s: Refusing to overwrite existing directory: %s", err_msg, err)
            return 1
        log.info(
            "Copied files from TemplateDir '%s' to '%s'", template_dir, paths.subdir
        )
        return 0
    paths.subdir.mkdir(exist_ok=True)
    with open(paths.config, "w", encoding="utf-8") as file:
        DBConfig(paths).parser.write(file)
        log.info("Created default configuration file: %s", paths.config)
    return 0


@_sc_runner
def traverse_sc(cla: argparse.Namespace, config: GlobalConfig) -> int:
    """Traverse sub-command"""
    return _run_op(cla, config, traverse_settings, traverse_op, get_db_config="acquire")


def traverse_settings(cla: argparse.Namespace, db_config: DBConfig) -> TraverseSettings:
    """Merge settings for traverse operation."""
    output_file = cla.output or db_config.get_path("db", "CSVName")
    path_field = db_config.parser["db"]["PathField"]
    count_field = db_config.parser["db"]["CountField"]
    tag_fields = db_config.get_list("db", "TagFields")

    return TraverseSettings(
        output_file=output_file,
        collection_root=db_config.paths.collection,
        force=cla.force,
        leaves_only=cla.leaves,
        path_field=path_field,
        count_field=count_field,
        tag_fields=tag_fields,
    )


def traverse_op(settings: TraverseSettings) -> int:
    """Traverse operation"""
    filename = settings["output_file"]
    if isinstance(filename, Path) and not settings["force"] and filename.exists():
        log.error("Refusing to overwrite existing CSV file: %s", filename)
        return 1
    path_field = settings["path_field"]
    count_field = settings["count_field"]
    tag_fields = settings["tag_fields"]
    fieldnames = [path_field, count_field, *tag_fields]
    log.debug(
        "path field: %r; count field: %r; tag fields: %r",
        path_field,
        count_field,
        tag_fields,
    )
    galleries = refresh.traverse_main(
        settings["collection_root"],
        path_field=path_field,
        count_field=count_field,
        leaves_only=settings["leaves_only"],
    )
    try:
        util.write_galleries(galleries, fieldnames=fieldnames, file=filename)
    except OSError as err:
        log.error("Unable to open CSV file for writing: %s", err)
        return 1
    log.info(
        "Wrote CSV to file: %s", "<stdout>" if filename == sys.stdout else filename
    )
    return 0


@_sc_runner
def count_sc(cla: argparse.Namespace, config: GlobalConfig) -> int:
    """Count sub-command"""
    return _run_op(cla, config, count_settings, count_op)


def count_settings(cla: argparse.Namespace, db_config: DBConfig) -> CountSettings:
    """Merge settings for count operation."""
    input_file = cla.csvfile or db_config.get_path("db", "CSVName")
    tag_fields = cla.fields or db_config.get_list("count", "TagFields")

    return CountSettings(
        input_file=input_file, tag_fields=tag_fields, summarize=cla.summarize
    )


def count_op(settings: CountSettings) -> int:
    """Count operation"""
    tag_fields = settings["tag_fields"]
    func = tagcount.summarize if settings["summarize"] else tagcount.count
    with _read_db(settings["input_file"], tag_fields) as reader:
        tag_sets = (gallery.merge_tags(*tag_fields) for gallery in reader)
        return func(tag_sets)


@_sc_runner
def query_sc(cla: argparse.Namespace, config: GlobalConfig) -> int:
    """Query sub-command"""
    return _run_op(cla, config, query_settings, query_op)


def query_settings(cla: argparse.Namespace, db_config: DBConfig) -> QuerySettings:
    """Merge settings for query operation."""
    input_file = cla.csvfile or db_config.get_path("db", "CSVName")
    tag_fields = cla.field or db_config.get_list("query", "TagFields")
    fmt: table_query.Format | None = cla.format
    if cla.field_formats:
        fmt = table_query.Format.FORMAT
    elif cla.rich_table:
        fmt = table_query.Format.RICH
    if fmt is None:
        try:
            fmt = table_query.Format(db_config.parser["query"]["Format"].lower())
        except ValueError as err:
            log.error("Invalid configuration setting: %s", err)
            raise _CLIError from err
    try:
        auto_fmt = table_query.Format(db_config.parser["query"]["AutoFormat"].lower())
    except ValueError as err:
        log.error("Invalid configuration setting: %s", err)
        raise _CLIError from err
    if auto_fmt not in {table_query.Format.FORMAT, table_query.Format.RICH}:
        log.error("Invalid configuration setting for AutoFormat: %s", fmt.value)
        raise _CLIError
    fmts_file = Path(cla.field_formats or db_config.get_path("query", "FieldFormats"))
    table_file = Path(cla.rich_table or db_config.get_path("query", "RichTable"))

    return QuerySettings(
        term=cla.term,
        sort_field=cla.sort,
        reverse_sort=cla.reverse,
        format=fmt,
        field_formats=fmts_file,
        rich_table=table_file,
        auto_format=auto_fmt,
        input_file=input_file,
        tag_fields=tag_fields,
    )


def query_op(settings: QuerySettings) -> int:
    """Query operation"""
    output_formatter = _query_output_formatter(settings)
    with _read_db(settings["input_file"]) as reader:
        query = table_query.query_from_args(
            settings["term"], reader.fieldnames, settings["tag_fields"]
        )
        galleries = table_query.sort_table(
            (gallery for gallery in reader if query.match(gallery)),
            reader.fieldnames,
            sort_field=settings["sort_field"],
            reverse_sort=settings["reverse_sort"],
        )
        table_query.print_table(galleries, reader.fieldnames, output_formatter)
    return 0


def _query_output_formatter(
    settings: QuerySettings,
) -> table_query.TablePrinter | None:
    """Sub-function of ``query_op``

    Return a ``TablePrinter`` that can print galleries, or return ``None``
    if no formatting was requested.
    """
    fmt = settings["format"]
    if fmt == table_query.Format.AUTO:
        if sys.stdout.isatty():
            fmt = settings["auto_format"]
        else:
            fmt = table_query.Format.NONE
    if fmt == table_query.Format.FORMAT:
        try:
            field_fmts = table_query.parse_field_format_file(settings["field_formats"])
        except OSError as err:
            log.error("Unable to read FieldFormats file: %s", err)
            raise _CLIError from err
        except UnicodeDecodeError as err:
            log.error(
                "Unable to decode FieldFormats file: %s: %s",
                err,
                settings["field_formats"],
            )
            raise _CLIError from err
        return table_query.FormattedTablePrinter(field_fmts)
    if fmt == table_query.Format.RICH:
        table_file = settings["rich_table"]
        return table_query.parse_rich_table_file(table_file)
    # fmt == table_query.Format.NONE
    return None


@_sc_runner
def refresh_sc(cla: argparse.Namespace, config: GlobalConfig) -> int:
    """Refresh sub-command"""
    return _run_op(cla, config, refresh_settings, refresh_op, get_db_config="acquire")


def refresh_settings(cla: argparse.Namespace, db_config: DBConfig) -> RefreshSettings:
    """Merge settings for refresh operation."""
    input_file = db_config.get_path("db", "CSVName")
    tag_fields = db_config.get_list("refresh", "TagFields")
    backup_suffix = cla.suffix or db_config.parser["refresh"]["BackupSuffix"]
    path_field = db_config.parser["refresh"]["PathField"]
    count_field = db_config.parser["refresh"]["CountField"]
    sort_spec = db_config.sort_spec("refresh", path_field)
    unique_fields = db_config.get_list("refresh", "UniqueFields")
    implications = db_config.get_multi_paths("refresh", "Implications")
    aliases = db_config.get_multi_paths("refresh", "Aliases")
    removals = db_config.get_multi_paths("refresh", "Removals")
    unified = db_config.get_multi_paths("refresh", "TagActions")
    implicating_fields = db_config.get_implicating_fields()

    return RefreshSettings(
        input_file=input_file,
        collection_root=db_config.paths.collection,
        tag_fields=tag_fields,
        backup_suffix=backup_suffix,
        path_field=path_field,
        count_field=count_field,
        sort_spec=sort_spec,
        unique_fields=unique_fields,
        implications=implications,
        aliases=aliases,
        removals=removals,
        tag_actions=unified,
        implicating_fields=implicating_fields,
        no_check=cla.no_check,
        validate=cla.validate,
    )


def refresh_op(settings: RefreshSettings) -> int:
    """Refresh operation"""
    gardener = refresh.Gardener()
    filename = settings["input_file"]
    gardener.set_normalize_tags(*settings["tag_fields"])
    sort_spec = settings["sort_spec"]
    gardener.needed_fields.update(field for field, _ in sort_spec)
    path_field = settings["path_field"]
    if not settings["no_check"]:
        gardener.set_update_count(
            path_field, settings["count_field"], settings["collection_root"]
        )
    gardener.set_unique(*settings["unique_fields"])
    try:
        error_status = set_tag_actions(gardener, settings) and 1
    except (OSError, UnicodeDecodeError) as err:
        log.error("Unable to read tag file: %s", err)
        return 1
    if settings["validate"] or error_status:
        return error_status
    try:
        with _read_db(settings["input_file"], gardener.needed_fields) as reader:
            rows = list(gardener.garden_rows(reader))
    except refresh.FolderPathError as err:
        log.error("With %s value: %s", path_field, err)
        return 1
    except refresh.DuplicateValueError as err:
        log.error("Duplicate value in %s: %s", err.field, err.value)
        return 1
    if not rows:
        return 0
    util.sort_by_field(rows, prepare_sort_spec(sort_spec))
    backup_file = filename.replace(
        filename.with_name(filename.name + settings["backup_suffix"])
    )
    log.info("Backed up '%s' -> '%s'", filename, backup_file)
    try:
        util.write_galleries(
            rows,
            fieldnames=reader.fieldnames,
            file=filename,
            opener=opener_copy_mode(backup_file),
        )
    except OSError as err:
        log.error("Unable to open CSV file for writing: %s", err)
        return 1
    log.info("Success: Saved refreshed table to '%s'", filename)
    return 0


def set_tag_actions(gardener: refresh.Gardener, settings: RefreshSettings) -> int:
    """Sub-function of ``refresh_op``

    Responsible for loading tag actions/implications from file and adding them
    to the gardener.
    """
    implicating_fields = settings["implicating_fields"]
    for filename in settings["aliases"]:
        gardener.set_alias_tags(refresh.get_aliases(filename), *implicating_fields)
    for filename in settings["implications"]:
        gardener.set_imply_tags(refresh.get_implications(filename), *implicating_fields)
    if settings["removals"]:
        gardener.set_remove_tags(
            refresh.get_tags_from_file(*settings["removals"]), *implicating_fields
        )
    tao = refresh.TagActionsObject(default_tag_fields=implicating_fields)
    unified = settings["tag_actions"]
    for filename in unified:
        tao.read_file(filename)
    errors = 0
    for fields, implic in tao.implicators():
        log.debug("Validating implicator for field(s): %s", ", ".join(sorted(fields)))
        errors += refresh.validate_tag_actions(implic)
        gardener.set_implicator(implic, *fields)
    if unified:
        # List paths as DB-relative.
        paths = join_semicolon_list(
            str(p.relative_to(settings["collection_root"])) for p in unified
        )
        msg = "Found %d logical error%s in TagActions files: %s"
        log.info(msg, errors, "" if errors == 1 else "s", paths)
    return errors


def prepare_sort_spec(
    specs: Iterable[tuple[str, bool]],
) -> list[tuple[util.KeyFunc, bool]]:
    """Log and transform sort specs."""
    specs_out: list[tuple[util.KeyFunc, bool]] = []
    msg = "Sorting by [%d]: %s, %s"
    for idx, (fieldname, reverse) in enumerate(specs):
        log.debug(msg, idx, fieldname, "descending" if reverse else "ascending")
        specs_out.append((util.field_key_func(fieldname), reverse))
    return specs_out


@_sc_runner
def related_sc(cla: argparse.Namespace, config: GlobalConfig) -> int:
    """Related sub-command"""
    return _run_op(cla, config, related_settings, related_op)


def related_settings(cla: argparse.Namespace, db_config: DBConfig) -> RelatedSettings:
    """Merge settings for related operation."""
    tag_fields = cla.field or db_config.get_list("related", "TagFields")
    input_file = cla.csvfile or db_config.get_path("related", "CSVName")
    limit: int | None = cla.limit
    sort_by: str | None = cla.sort
    if limit is None:
        try:
            limit = db_config.parser["related"].getint("Limit")
        except ValueError as err:
            log.error("Invalid configuration setting for Limit: %s", err)
            raise _CLIError from err
    if sort_by is None:
        sort_by = db_config.parser["related"]["SortMetric"].lower()
        if sort_by not in relatedtag.SimilarityResult.choices():
            log.error("Invalid configuration setting for SortMetric: %s", sort_by)
            raise _CLIError

    return RelatedSettings(
        input_file=input_file,
        tag_fields=tag_fields,
        limit_results=limit,
        sort_metric=sort_by,
        term=cla.term,
    )


def related_op(settings: RelatedSettings) -> int:
    """Related operation"""
    input_file = settings["input_file"]
    tag_fields = settings["tag_fields"]
    with _read_db(input_file, tag_fields) as reader:
        query = table_query.query_from_args(
            settings["term"], reader.fieldnames, tag_fields
        )
        related_tags = relatedtag.get_related_tags(reader, query, frozenset(tag_fields))
        similarity_results = relatedtag.sort(
            related_tags, sort_by=settings["sort_metric"], n=settings["limit_results"]
        )
    log.debug("Read from CSV file %r", input_file)
    relatedtag.print_results(similarity_results)
    return 0


def log_field_mismatch(error: util.FieldMismatchError) -> None:
    log.error("Error in CSV file: %s", error)
    log.debug("Fieldnames from file: %s", error.fieldnames)


def ignore_patterns(*patterns: StrPath) -> Callable[[Any, list[str]], set[str]]:
    """
    Return a function that wraps ``shutil.ignore_patterns`` with a layer of
    debug logging.
    """
    ignore_func = shutil.ignore_patterns(*patterns)

    def _inner_func(path: Any, names: list[str]) -> set[str]:
        names_in = set(names)
        names_ignored = ignore_func(path, names)
        log.debug("Copying files: %s", names_in - names_ignored)
        log.debug("Filenames ignored: %s", names_ignored)
        return names_ignored

    return _inner_func


def opener_copy_mode(path: StrPath) -> Callable[[StrPath, int], int]:
    """Return an "opener" for opening a file with the same mode as *path*."""
    mode_bits = stat.S_IMODE(os.stat(path).st_mode)

    def _opener(path: StrPath, flags: int) -> int:
        return os.open(path, flags, mode=mode_bits)

    log.debug(
        "A custom opener was created by copying mode bits %o from %s", mode_bits, path
    )
    return _opener


def _run_op(
    cla: ArgsT,
    config: GlobalConfig,
    settings_func: Callable[[ArgsT, DBConfig], SettingsT],
    op_func: Callable[[SettingsT], int],
    get_db_config: Literal["get", "acquire"] = "get",
) -> int:
    """Get or acquire configuration, and run *op_func*."""
    paths = config.get_collections().find_collection(cla.collection)
    if get_db_config == "acquire":
        db_config = paths.acquire_db_config()
        if not db_config:
            return 1
    else:
        db_config = paths.get_db_config()
    settings = settings_func(cla, db_config)
    return op_func(settings)


@contextlib.contextmanager
def _read_db(
    file: StrPath | Iterable[str], fieldnames: Iterable[str] | None = None
) -> Iterator[util.Reader]:
    """Try to read DB from *file*, raising ``_CLIError`` on error."""
    try:
        with util.read_db(file=file, fieldnames=fieldnames) as reader:
            yield reader
    except BrokenPipeError as err:
        # Even though BrokenPipeError was caught, suppress the error
        # message by closing stderr before exiting.
        sys.stderr.close()
        raise _CLIError(0) from err
    except refresh.FolderPathError:
        # Error is handled at higher level. Re-raise, otherwise exception is
        # caught by 'except OSError' block below.
        raise
    except (OSError, csv.Error) as err:
        log.error("Unable to read CSV file: %s", err)
        raise _CLIError from err
    except UnicodeDecodeError as err:
        file_name = "<stdin>" if file == sys.stdin else file
        log.error("Unable to decode CSV file: %s: %s", err, file_name)
        raise _CLIError from err
    except util.FieldNotFoundError as err:
        log.error("Field not in file: %s", err)
        raise _CLIError from err
    except table_query.TableQueryError as err:
        # Error is logged by table_query module.
        raise _CLIError from err
    except util.FieldMismatchError as err:
        log_field_mismatch(err)
        raise _CLIError from err
