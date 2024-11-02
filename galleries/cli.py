#!/usr/bin/python3
#
# cli.py
#
"""Command-line interface"""

from __future__ import annotations

import argparse
import configparser
import contextlib
import dataclasses
import logging
import os
import shutil
import sys
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, TextIO

from . import PROG, __version__, refresh, relatedtag, table_query, tagcount, util

StrPath = str | Path

DB_DIR_NAME = ".galleries"
DB_CONFIG_NAME = "db.conf"
DEFAULT_PATH_SPEC = {"GalleriesDir": DB_DIR_NAME, "ConfigName": DB_CONFIG_NAME}
DEFAULT_GLOBAL_CONFIG: dict[str, dict[str, Any]] = {
    "global": {"Verbose": False},
    "init": {},
}
DEFAULT_CONFIG_STATE: dict[str, dict[str, Any]] = {
    "db": {
        "CSVName": "db.csv",
        "TagFields": "Tags",
        "PathField": "Path",
        "CountField": "Count",
    },
    "refresh": {"BackupSuffix": ".bak", "ReverseSort": False},
    "count": {},
    "query": {
        "Format": "none",
        "AutoFormat": "format",
        "FieldFormats": "tableformat.conf",
        "RichTable": "richtable.toml",
    },
    "related": {"SortMetric": "cosine", "Filter": "", "Limit": 20},
}

log = logging.getLogger(PROG)


class FileType:
    """
    Reduced version of ``argparse.FileType``. Only checks for special argument
    "-" meaning stdin (for mode "r") or stdout (for mode "w").
    """

    def __init__(self, mode: str = "r") -> None:
        self.mode = mode

    def __call__(self, string: str) -> str | TextIO:
        if string == "-":
            if "r" in self.mode:
                return sys.stdin
            if "w" in self.mode:
                return sys.stdout
            msg = f"argument '-' with mode {self.mode}"
            raise ValueError(msg)
        return string

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.mode!r})"


class GlobalConfig:
    def __init__(
        self,
        options_p: configparser.ConfigParser | None = None,
        collections_p: configparser.ConfigParser | None = None,
    ) -> None:
        if options_p is None:
            self.options = configparser.ConfigParser(interpolation=None)
        else:
            self.options = options_p
        if collections_p is None:
            self.collections = configparser.ConfigParser(
                defaults=DEFAULT_PATH_SPEC,
                interpolation=configparser.ExtendedInterpolation(),
            )
        else:
            self.collections = collections_p

    def get_collections(self) -> CollectionFinder:
        try:
            default_collection = self.options["global"]["Default"]
        except KeyError:
            default_collection = None
        else:
            if not self.collections.has_section(default_collection):
                log.warning(
                    "Default collection not found in collections: %s",
                    default_collection,
                )
                default_collection = None
        finder = CollectionFinder(
            default_settings=self.collections[self.collections.default_section],
            default_name=default_collection,
        )
        for section in self.collections.sections():
            if path_spec := self._spec_from_section(section):
                finder.add_collection(path_spec)
        return finder

    def _spec_from_section(self, section: str) -> CollectionPathSpec | None:
        try:
            root = self.collections[section]["Root"]
        except KeyError:
            log.warning(
                "Ignoring collection [%s]: Required key is missing: Root", section
            )
            return None
        except configparser.InterpolationError as err:
            log.warning("Ignoring collection [%s]: %s", section, err)
            return None
        collection_path = Path(root).expanduser()
        if not collection_path.is_absolute():
            log.warning(
                "Ignoring collection [%s]: Root is not an absolute path: %s",
                section,
                collection_path,
            )
            return None
        try:
            return collection_path_spec(
                collection_path=collection_path,
                subdir_name=self.collections[section]["GalleriesDir"],
                config_name=self.collections[section]["ConfigName"],
                name=section,
            )
        except configparser.InterpolationError as err:
            log.warning("Ignoring collection [%s]: %s", section, err)
            return None


class DBConfig:
    """Helper for parsing the DB configuration"""

    def __init__(
        self,
        paths: CollectionPathSpec,
        parser: configparser.ConfigParser | None = None,
    ) -> None:
        self.paths = paths
        if parser is None:
            self.parser = configparser.ConfigParser(
                default_section="db", interpolation=None
            )
        else:
            self.parser = parser
        self.parser.read_dict(DEFAULT_CONFIG_STATE)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(paths={self.paths}, parser={self.parser})"

    def get_list(self, section: str, option: str, **kwds: Any) -> list[str]:
        return split_semicolon_list(self.parser.get(section, option, **kwds))

    def get_path(self, section: str, option: str, **kwds: Any) -> Path:
        return self.paths.get_db_path(self.parser.get(section, option, **kwds))

    def get_multi_paths(self, section: str, option: str) -> list[Path]:
        if val := self.parser[section].get(option):
            return [self.paths.get_db_path(name) for name in split_semicolon_list(val)]
        return []

    def get_implicating_fields(self, tag_fields: list[str] | None = None) -> set[str]:
        if tag_fields is None:
            tag_fields = self.get_list("refresh", "TagFields")
        implicating_fields = set(tag_fields)
        if val := self.parser["refresh"].get("ImplicatingFields"):
            arguments = frozenset(split_semicolon_list(val))
            if not arguments.issubset(implicating_fields):
                log.warning(
                    "In %s: ImplicatingFields is not a subset of TagFields",
                    self.paths.config,
                )
            implicating_fields &= arguments
        return implicating_fields


@dataclasses.dataclass(frozen=True)
class CollectionPathSpec:
    """The set of paths describing a collection, optionally named"""

    name: str | None
    collection: Path
    subdir: Path
    config: Path

    def get_db_path(self, filename: StrPath) -> Path:
        return self.subdir / filename

    # In acquire_db_config and get_db_config, don't try to handle and recover
    # from configparser errors. The parser will not be in a readable state.
    # Log the error and re-raise the exception.

    def acquire_db_config(self) -> DBConfig | None:
        """Check collection's validity, and read its configuration.

        If this path spec represents a valid collection, one with a working
        config file, read it, construct and return ``DBConfig``, else return
        ``None``.
        """
        if not self.config.is_file():
            log.error("No valid collection found at path: %s", self.config)
            return None
        config = DBConfig(paths=self)
        try:
            successful = config.parser.read(self.config)
        except configparser.Error as err:
            self._log_bad_read(err)
            raise
        if not successful:
            self._log_bad_read(self.config)
            return None
        return config

    def get_db_config(self) -> DBConfig:
        config = DBConfig(paths=self)
        try:
            config.parser.read(self.config)
        except configparser.Error as err:
            self._log_bad_read(err)
            raise
        return config

    @staticmethod
    def _log_bad_read(error: object) -> None:
        return log.error("Unable to read configuration from file: %s", error)


class CollectionFinder:
    """Maintain the data needed to create ``CollectionPathSpec``s."""

    def __init__(
        self,
        collections: Iterable[CollectionPathSpec] | None = None,
        default_name: str | None = None,
        default_settings: Mapping[str, Any] | None = None,
    ) -> None:
        self.default_name = default_name
        if default_settings is not None:
            self.default_settings = default_settings
        else:
            self.default_settings = DEFAULT_PATH_SPEC
        self._collection_names: dict[str, CollectionPathSpec] = {}
        self._collection_paths: dict[Path, CollectionPathSpec] = {}
        if collections is not None:
            for spec in collections:
                self.add_collection(spec)

    def add_collection(self, path_spec: CollectionPathSpec) -> None:
        if path_spec.name is not None:
            self._collection_names[path_spec.name] = path_spec
        self._collection_paths[path_spec.collection] = path_spec

    def _disambiguate_collection_name(self, name: str) -> CollectionPathSpec | None:
        if exact_match := self._collection_names.get(name):
            log.debug("arg matches name exactly: %s", exact_match)
            return exact_match
        name = name.casefold()
        prefix_matches = [
            coll for coll in self._collection_names if coll.casefold().startswith(name)
        ]
        if prefix_matches:
            prefix_match = self._collection_names[min(prefix_matches)]
            log.debug("arg matches name prefix: %s", prefix_match)
            return prefix_match
        return None

    def find_collection(self, arg: str | None = None) -> CollectionPathSpec:
        """Return the path spec determined by *arg*."""
        if arg:
            return self._lookup_collection(arg)
        cwd = Path.cwd()
        if path_lookup := self._collection_paths.get(cwd):
            log.debug("cwd matches collection path: %s", path_lookup)
            return path_lookup
        if self.default_name:
            with contextlib.suppress(KeyError):
                default_collection = self._collection_names[self.default_name]
                log.debug("using default collection: %s", default_collection)
                return default_collection
        default_collection = self.anonymous_collection(cwd)
        log.debug("using cwd: %s", default_collection)
        return default_collection

    def _lookup_collection(self, arg: str) -> CollectionPathSpec:
        if name_lookup := self._disambiguate_collection_name(arg):
            return name_lookup
        path = Path(arg).resolve()
        if path_lookup := self._collection_paths.get(path):
            log.debug("arg matches collection path: %s", path_lookup)
            return path_lookup
        as_path = self.anonymous_collection(arg)
        log.debug("using path value of arg: %s", as_path)
        return as_path

    def anonymous_collection(self, collection_path: StrPath) -> CollectionPathSpec:
        """Return the default path spec rooted in *collection_path*."""
        return collection_path_spec(
            collection_path=collection_path,
            subdir_name=self.default_settings["GalleriesDir"],
            config_name=self.default_settings["ConfigName"],
        )

    def collections_added(self) -> set[CollectionPathSpec]:
        return set(self._collection_paths.values())


class _CLIError(Exception):
    """Some kind of fatal error"""

    def __init__(self, status: int = 1) -> None:
        super().__init__(status)
        self.status = status


def path_sc(cla: argparse.Namespace, config: GlobalConfig) -> int:
    """Path sub-command"""
    collection = config.get_collections().find_collection(cla.collection)
    print(collection.collection)
    return 0


def init_sc(cla: argparse.Namespace, global_config: GlobalConfig) -> int:
    """Init sub-command"""
    err_msg = "Unable to init"
    root = Path(cla.directory or cla.collection or Path.cwd())
    if not root.is_dir():
        try:
            root.mkdir(parents=True, exist_ok=False)
        except OSError as err:
            log.error("%s: Failed to create root directory: %s", err_msg, err)
            return 1
        log.info("Created root directory: %s", root)
    paths = global_config.get_collections().find_collection(str(root))
    if paths.config.exists():
        log.error(
            "%s: Refusing to overwrite existing configuration file: %s",
            err_msg,
            paths.config,
        )
        return 1
    if cla.bare:
        paths.subdir.mkdir(exist_ok=True)
        paths.config.touch(exist_ok=False)
        log.info("Created empty configuration file: %s", paths.config)
        return 0
    if template_dir := cla.template or global_config.options["init"].get("TemplateDir"):
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


def traverse_sc(cla: argparse.Namespace, config: GlobalConfig) -> int:
    """Traverse sub-command"""
    paths = config.get_collections().find_collection(cla.collection)
    db_config = paths.acquire_db_config()
    if not db_config:
        return 1
    filename = cla.output
    if not filename:
        filename = db_config.get_path("db", "CSVName")
        if not cla.force and filename.exists():
            log.error("Refusing to overwrite existing CSV file: %s", filename)
            return 1
    path_field = db_config.parser.get("db", "PathField")
    count_field = db_config.parser.get("db", "CountField")
    tag_fields = db_config.get_list("db", "TagFields")
    fieldnames = [path_field, count_field, *tag_fields]
    log.debug(
        "path field: %r; count field: %r; tag fields: %r",
        path_field,
        count_field,
        tag_fields,
    )
    galleries = refresh.traverse_main(
        paths.collection,
        path_field=path_field,
        count_field=count_field,
        leaves_only=cla.leaves,
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


def count_sc(cla: argparse.Namespace, config: GlobalConfig) -> int:
    """Count sub-command"""
    db_config = config.get_collections().find_collection(cla.collection).get_db_config()
    filename = cla.csvfile or db_config.get_path("db", "CSVName")
    tag_fields = cla.fields or db_config.get_list("count", "TagFields")
    func = tagcount.summarize if cla.summarize else tagcount.count
    try:
        with _read_db(filename, tag_fields) as reader:
            tag_sets = (gallery.merge_tags(*tag_fields) for gallery in reader)
            return func(tag_sets)
    except _CLIError as err:
        return err.status


def query_sc(cla: argparse.Namespace, config: GlobalConfig) -> int:
    """Query sub-command"""
    db_config = config.get_collections().find_collection(cla.collection).get_db_config()
    filename = cla.csvfile or db_config.get_path("db", "CSVName")
    tag_fields = cla.field or db_config.get_list("query", "TagFields")
    try:
        output_formatter = _query_output_formatter(cla, db_config)
    except _CLIError as err:
        return err.status
    try:
        with _read_db(filename) as reader:
            query = table_query.query_from_args(cla.term, reader.fieldnames, tag_fields)
            galleries = table_query.sort_table(
                (gallery for gallery in reader if query.match(gallery)),
                reader.fieldnames,
                sort_field=cla.sort,
                reverse_sort=cla.reverse,
            )
            table_query.print_table(galleries, reader.fieldnames, output_formatter)
    except _CLIError as err:
        return err.status
    return 0


def _query_output_formatter(
    cla: argparse.Namespace, config: DBConfig
) -> table_query.TablePrinter | None:
    """Sub-function of ``query_sc``

    Return a ``TablePrinter`` that can print galleries, or return ``None``
    if no formatting was requested.
    """
    fmt = cla.format
    if cla.field_formats:
        fmt = table_query.Format.FORMAT
    elif cla.rich_table:
        fmt = table_query.Format.RICH
    if fmt is None:
        try:
            fmt = table_query.Format(config.parser.get("query", "Format").lower())
        except ValueError as err:
            log.error("Invalid configuration setting: %s", err)
            raise _CLIError from err
    if fmt == table_query.Format.AUTO:
        if sys.stdout.isatty():
            try:
                fmt = table_query.Format(
                    config.parser.get("query", "AutoFormat").lower()
                )
            except ValueError as err:
                log.error("Invalid configuration setting: %s", err)
                raise _CLIError from err
            if fmt not in {table_query.Format.FORMAT, table_query.Format.RICH}:
                log.error("Invalid configuration setting for AutoFormat: %s", fmt.value)
                raise _CLIError
        else:
            fmt = table_query.Format.NONE
    if fmt == table_query.Format.FORMAT or cla.field_formats:
        fmts_file = cla.field_formats or config.get_path("query", "FieldFormats")
        try:
            field_fmts = table_query.parse_field_format_file(fmts_file)
        except (OSError, UnicodeDecodeError) as err:
            log.error("Unable to read FieldFormats file: %s", err)
            raise _CLIError from err
        return table_query.FormattedTablePrinter(field_fmts)
    if fmt == table_query.Format.RICH or cla.rich_table:
        table_file = cla.rich_table or config.get_path("query", "RichTable")
        return table_query.parse_rich_table_file(table_file)
    # fmt == table_query.Format.NONE
    return None


def refresh_sc(cla: argparse.Namespace, config: GlobalConfig) -> int:
    """Refresh sub-command"""
    paths = config.get_collections().find_collection(cla.collection)
    db_config = paths.acquire_db_config()
    if not db_config:
        return 1
    gardener = refresh.Gardener()
    # First, acquire all "guaranteed" values.
    filename = db_config.get_path("db", "CSVName")
    tag_fields = db_config.get_list("refresh", "TagFields")
    gardener.set_normalize_tags(*tag_fields)
    backup_suffix = cla.suffix or db_config.parser.get("refresh", "BackupSuffix")
    # Second, acquire values for Update file count, if requested
    path_field = db_config.parser.get("refresh", "PathField")
    count_field = db_config.parser.get("refresh", "CountField")
    sort_field = db_config.parser["refresh"].get("SortField", path_field)
    gardener.needed_fields.add(sort_field)
    if not cla.no_check:
        gardener.set_update_count(path_field, count_field, paths.collection)
    # Third, see if there are enough values to perform implication
    try:
        error_status = set_tag_actions(gardener, db_config) and 1
    except (OSError, UnicodeDecodeError) as err:
        log.error("Unable to read tag file: %s", err)
        return 1
    if cla.validate or error_status:
        return error_status
    try:
        with util.read_db(filename, gardener.needed_fields) as reader:
            rows = list(gardener.garden_rows(reader))
    except refresh.FolderPathError as err:
        log.error("With %s value: %s", path_field, err)
        return 1
    except (OSError, UnicodeDecodeError) as err:
        log.error("Unable to read CSV file: %s", err)
        return 1
    except util.FieldNotFoundError as err:
        log.error("Field not in file: %s", err)
        return 1
    except util.FieldMismatchError as err:
        log_field_mismatch(err)
        return 1
    if not rows:
        return 0
    try:
        reverse = db_config.parser["refresh"].getboolean("ReverseSort")
    except ValueError as err:
        log.warning(
            "Invalid configuration setting for ReverseSort (defaulting to False): %s",
            err,
        )
        reverse = False
    log.debug("Sorting by field: %s", sort_field)
    rows.sort(key=util.alphanum_getter(sort_field), reverse=reverse)
    backup_file = filename.replace(filename.with_name(filename.name + backup_suffix))
    log.info("Backed up '%s' -> '%s'", filename, backup_file)
    try:
        util.write_galleries(rows, fieldnames=reader.fieldnames, file=filename)
    except OSError as err:
        log.error("Unable to open CSV file for writing: %s", err)
        return 1
    log.info("Success: Saved refreshed table to '%s'", filename)
    return 0


def set_tag_actions(gardener: refresh.Gardener, config: DBConfig) -> int:
    """Sub-function of ``refresh_sc``

    Responsible for loading tag actions/implications from file and adding them
    to the gardener.
    """
    implications = config.get_multi_paths("refresh", "Implications")
    aliases = config.get_multi_paths("refresh", "Aliases")
    removals = config.get_multi_paths("refresh", "Removals")
    unified = config.get_multi_paths("refresh", "TagActions")
    implicating_fields = config.get_implicating_fields()
    for filename in aliases:
        gardener.set_alias_tags(refresh.get_aliases(filename), *implicating_fields)
    for filename in implications:
        gardener.set_imply_tags(refresh.get_implications(filename), *implicating_fields)
    if removals:
        gardener.set_remove_tags(
            refresh.get_tags_from_file(*removals), *implicating_fields
        )
    tao = refresh.TagActionsObject(default_tag_fields=implicating_fields)
    for filename in unified:
        tao.read_file(filename)
    errors = 0
    for fields, implic in tao.implicators():
        log.debug("Validating implicator for field(s): %s", ", ".join(sorted(fields)))
        errors += refresh.validate_tag_actions(implic)
        gardener.set_implicator(implic, *fields)
    msg = "Found %d logical error%s in TagActions files: %s"
    paths = join_semicolon_list(config.get_list("refresh", "TagActions"))
    log.info(msg, errors, "" if errors == 1 else "s", paths)
    return errors


def related_sc(cla: argparse.Namespace, config: GlobalConfig) -> int:
    """Related sub-command"""
    db_config = config.get_collections().find_collection(cla.collection).get_db_config()
    tag_fields = cla.field or db_config.get_list("related", "TagFields")
    input_file = cla.csvfile or db_config.get_path("related", "CSVName")
    limit = cla.limit
    sort_by = cla.sort
    search_terms = cla.where or db_config.get_list("related", "Filter")
    if limit is None:
        try:
            limit = db_config.parser.getint("related", "Limit")
        except ValueError as err:
            log.error("Invalid configuration setting for Limit: %s", err)
            return 1
    if sort_by is None:
        sort_by = db_config.parser.get("related", "SortMetric").lower()
        if sort_by not in relatedtag.SimilarityResult.choices():
            log.error("Invalid configuration setting for SortMetric: %s", sort_by)
            return 1

    try:
        with _read_db(input_file, tag_fields) as reader:
            if search_terms:
                query = table_query.query_from_args(
                    search_terms, reader.fieldnames, tag_fields
                )
                galleries = (gallery for gallery in reader if query.match(gallery))
            else:
                galleries = reader
            tag_sets = (gallery.merge_tags(*tag_fields) for gallery in galleries)
            overlap_table = relatedtag.overlap_table(tag_sets)
    except _CLIError as err:
        return err.status
    log.debug("Read from CSV file %r", input_file)
    relatedtag.print_relatedtags(overlap_table, cla.tags, sort_by=sort_by, limit=limit)
    return 0


def build_cla_parser() -> argparse.ArgumentParser:
    """Build and return command-line argument parser."""
    top_level = argparse.ArgumentParser(add_help=False)
    top_level.set_defaults(func=path_sc)
    subparsers = top_level.add_subparsers(
        title="commands",
        description="'%(prog)s COMMAND --help' shows help message for COMMAND.",
    )

    init_p = subparsers.add_parser(
        "init",
        help="initialize a new collection",
        description="Initialize a new collection rooted in DIRECTORY, create new config file.",
    )
    init_p.add_argument(
        "directory",
        metavar="DIRECTORY",
        nargs="?",
        help="path to root directory of collection (default is current directory)",
    )
    init_p.add_argument(
        "--bare", action="store_true", help="create an empty config file"
    )
    init_p.add_argument(
        "--template",
        metavar="SRC",
        help="copy files from %(metavar)s into sub-directory of DIRECTORY",
    )
    init_p.set_defaults(func=init_sc)

    traverse_p = subparsers.add_parser(
        "traverse",
        help="enumerate directory tree",
        description="Enumerate directory tree of COLLECTION, create new CSV file.",
    )
    traverse_p.add_argument(
        "--force", action="store_true", help="overwrite existing CSV file"
    )
    traverse_p.add_argument(
        "--leaves",
        action="store_true",
        help="only enumerate directories with no sub-directories",
    )
    traverse_p.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        type=FileType("w"),
        help="write CSV to %(metavar)s (use '-' for standard output)",
    )
    traverse_p.set_defaults(func=traverse_sc)

    count_p = subparsers.add_parser(
        "count",
        help="count total tags",
        description="Print counts of all tags occuring in tag field(s).",
    )
    count_p.add_argument(
        "fields",
        nargs="*",
        metavar="FIELD",
        help="use %(metavar)s(s) instead of default TagFields",
    )
    count_p.add_argument(
        "-i",
        "--input",
        metavar="FILE",
        dest="csvfile",
        type=FileType(),
        help="read CSV from %(metavar)s (use '-' for standard input)",
    )
    count_p.add_argument(
        "-S",
        "--summarize",
        action="store_true",
        help="print statistical summary of tag counts",
    )
    count_p.set_defaults(func=count_sc)

    query_p = subparsers.add_parser(
        "query",
        help="query the table",
        description=(
            "Print galleries matching search term(s)."
            f" Wildcard is '{table_query.ArgumentParser.wildcard}',"
            f" NOT prefix is '{table_query.ArgumentParser.not_operator}',"
            f" OR prefix is '{table_query.ArgumentParser.or_operator}'."
        ),
    )
    query_p.add_argument(
        "-f",
        "--field",
        metavar="FIELD",
        action="append",
        help="search field %(metavar)s(s) instead of default TagFields",
    )
    query_p.add_argument(
        "-F",
        "--format",
        nargs="?",
        type=table_query.Format.argparse,
        const=table_query.Format.AUTO.value,
        choices=list(table_query.Format),
        help="control output format",
    )
    query_p.add_argument(
        "-i",
        "--input",
        metavar="FILE",
        dest="csvfile",
        type=FileType(),
        help="read CSV from %(metavar)s (use '-' for standard input)",
    )
    query_p.add_argument(
        "-r", "--reverse", action="store_true", help="reverse order while sorting"
    )
    query_p.add_argument(
        "-s", "--sort", metavar="FIELD", help="sort results by %(metavar)s"
    )
    output_format = query_p.add_mutually_exclusive_group()
    output_format.add_argument(
        "--field-formats", metavar="FILE", help="parse field formats from %(metavar)s"
    )
    output_format.add_argument(
        "--rich-table",
        metavar="FILE",
        help="parse Rich table settings from %(metavar)s",
    )
    query_p.add_argument("term", metavar="TERM", nargs="*", help="term(s) of search")
    query_p.set_defaults(func=query_sc)

    refresh_p = subparsers.add_parser(
        "refresh",
        help="update the table",
        description="Update galleries' info, garden tags.",
    )
    refresh_p.add_argument("--suffix", help="override the usual backup suffix")
    refresh_p.add_argument(
        "--no-check",
        action="store_true",
        help="skip PathField checks/CountField updates",
    )
    refresh_p.add_argument(
        "--validate",
        action="store_true",
        help="check TagActions files for correctness and exit",
    )
    refresh_p.set_defaults(func=refresh_sc)

    related_p = subparsers.add_parser(
        "related",
        help="list related tags",
        description="Print frequently co-occurring tags",
    )
    related_p.add_argument(
        "tags", nargs="+", metavar="TAG", help="list tags similar to %(metavar)s(s)"
    )
    related_p.add_argument(
        "-f",
        "--field",
        metavar="NAME",
        action="append",
        help="analyze tags from %(metavar)s(s) instead of default TagFields",
    )
    related_p.add_argument(
        "-i",
        "--input",
        metavar="FILE",
        dest="csvfile",
        type=FileType("r"),
        help="read CSV from %(metavar)s (use '-' for standard input)",
    )
    related_p.add_argument(
        "-l",
        "--limit",
        metavar="N",
        type=int,
        help="limit number of results per TAG to %(metavar)s (0 for no limit)",
    )
    related_p.add_argument(
        "-s",
        "--sort",
        type=str.lower,
        choices=relatedtag.SimilarityResult.choices(),
        help="sort results by metric",
    )
    related_p.add_argument(
        "-w",
        "--where",
        metavar="TERM",
        action="append",
        help="filter galleries analyzed by search %(metavar)s(s)",
    )
    related_p.set_defaults(func=related_sc)

    general_opts = top_level.add_argument_group(title="general options")
    general_opts.add_argument(
        "-h", "--help", action="help", help="show this help message and exit"
    )
    general_opts.add_argument(
        "-V", "--version", action="version", version=f"{PROG} {__version__}"
    )
    general_opts.add_argument(
        "-c",
        "--collection",
        help="select collection, either by name or by path (default is current directory)",
    )
    verbosity = general_opts.add_mutually_exclusive_group()
    verbosity.add_argument(
        "-q", "--quiet", action="store_true", help="turn off verbose output"
    )
    verbosity.add_argument(
        "-v",
        "--verbose",
        action="count",
        help="turn on verbose output ('-vv' for debug output)",
    )

    return top_level


def main(args: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.DEBUG, format=f"{PROG}: %(levelname)s: %(message)s"
    )
    try:
        global_config = read_global_configuration()
    except configparser.Error:
        return 1
    args_ns = build_cla_parser().parse_args(args)
    set_logging_level(args_ns, global_config)
    log.debug(args_ns)
    try:
        return args_ns.func(args_ns, global_config)
    except configparser.Error:
        return 1


def set_logging_level(args: argparse.Namespace, global_config: GlobalConfig) -> None:
    verbosity = 0
    try:
        config_setting = global_config.options["global"].getboolean("Verbose")
    except ValueError as err:
        log.warning("Invalid global configuration setting for Verbose: %s", err)
        config_setting = False
    verbosity = 1 if config_setting else 0
    if args.verbose is not None:
        verbosity = args.verbose
    if args.quiet or verbosity == 0:
        logging.disable(logging.INFO)
    elif verbosity == 1:
        logging.disable(logging.DEBUG)
    # else: level remains at DEBUG


def get_global_config_dir() -> Path:
    if custom_path := os.getenv("GALLERIES_CONF"):
        return Path(custom_path).expanduser()
    if xdg_config_home := os.getenv("XDG_CONFIG_HOME"):
        base_dir = Path(xdg_config_home)
    else:
        base_dir = Path.home() / ".config"
    return base_dir / PROG


def collection_path_spec(
    collection_path: StrPath,
    subdir_name: StrPath,
    config_name: StrPath,
    name: str | None = None,
) -> CollectionPathSpec:
    collection_path = Path(collection_path)
    subdir_path = collection_path / subdir_name
    config_path = subdir_path / config_name
    return CollectionPathSpec(
        name=name, collection=collection_path, subdir=subdir_path, config=config_path
    )


def read_global_configuration() -> GlobalConfig:
    config_dir_path = get_global_config_dir()
    parser = GlobalConfig()
    parser.options.read_dict(DEFAULT_GLOBAL_CONFIG)
    # Don't try to recover from configparser.Error. The parser will not be in
    # a readable state.
    # Log the error and re-raise.
    err_msg = "Unable to read %s configuration file: %s"
    try:
        parser.options.read(config_dir_path / "config")
    except configparser.Error as err:
        log.error(err_msg, "global", err)
        raise
    try:
        parser.collections.read(config_dir_path / "collections")
    except configparser.Error as err:
        log.error(err_msg, "collections", err)
        raise
    return parser


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


def join_semicolon_list(items: Iterable[str]) -> str:
    return "; ".join(items)


def split_semicolon_list(value: str) -> list[str]:
    if not value:
        return []
    return [stripped for item in value.split(";") if (stripped := item.strip())]


@contextlib.contextmanager
def _read_db(
    file: os.PathLike | None = None, fieldnames: Iterable[str] | None = None
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
    except (OSError, UnicodeDecodeError) as err:
        log.error("Unable to read CSV file: %s", err)
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


if __name__ == "__main__":
    sys.exit(main())
