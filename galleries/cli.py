#!/usr/bin/python3
#
# cli.py
#
"""Command-line interface"""

from __future__ import annotations

import argparse
import configparser
import csv
import json
import logging
import math
import os
import shutil
import sys
from collections.abc import Iterable
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Optional, TextIO, Union

from . import __prog__, __version__, refresh, relatedtag, table_query, tagcount, util

DB_DIR_NAME = ".galleries"
DB_CONFIG_NAME = "db.conf"
DEFAULT_CONFIG_STATE: dict[str, dict[str, str]] = {
    "db": {
        "CSVName": "db.csv",
        "TagFields": "Tags",
        "PathField": "Path",
        "CountField": "Count",
    },
    "refresh": {"BackupSuffix": ".bak"},
    "count": {},
    "query": {
        "Format": "none",
        "FieldFormats": "tableformat.conf",
    },
    "overlaps": {},
    "freq": {"Limit": "20"},
}

log = logging.getLogger(__name__)


class FileType:
    """
    Reduced version of ``argparse.FileType``. Only checks for special argument
    "-" meaning stdin (for mode "r") or stdout (for mode "w").
    """

    def __init__(self, mode: str = "r") -> None:
        self.mode = mode

    def __call__(self, string: str) -> Union[str, TextIO]:
        if string == "-":
            if "r" in self.mode:
                return sys.stdin
            if "w" in self.mode:
                return sys.stdout
            raise ValueError(f"argument '-' with mode {self.mode}")
        return string

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.mode!r})"


class GlobalConfig:
    def __init__(
        self,
        collections: Optional[dict[str, Path]] = None,
        default: Optional[str] = None,
        verbose: Optional[bool] = None,
        init: Optional[Any] = None,
    ) -> None:
        self.collections = collections or {}
        self.default = default
        self.verbose = verbose
        self.init = init or {}

    def _disambiguate_collection_name(self, name: str) -> Optional[Path]:
        name = name.casefold()
        if exact_match := self.collections.get(name):
            return exact_match
        prefix_matches = [
            coll
            for coll in sorted(self.collections)
            if coll.casefold().startswith(name)
        ]
        if prefix_matches:
            return self.collections[prefix_matches[0]]
        return None

    def find_collection(self, name: Optional[str] = None) -> Path:
        """
        If *name* is given, look it up in collections. If missing, return
        *name* as a ``Path``.
        If *name* is not given, use default name or, if no default name,
        return current directory.
        """
        name = name or self.default
        if name:
            if lookup := self._disambiguate_collection_name(name):
                return lookup
            return Path(name)
        return Path.cwd()


class DBConfig(configparser.ConfigParser):
    """Parse the configuration for the collection rooted at *collection_path*."""

    def __init__(self, collection_path: Path, **kwds: Any) -> None:
        super().__init__(
            **kwds,
            default_section="db",
            interpolation=configparser.ExtendedInterpolation(),
        )
        self.collection_path = collection_path
        self.read_dict(DEFAULT_CONFIG_STATE)

    def get_list(self, section: str, option: str, **kwds: Any) -> list[str]:
        return split_semicolon_list(self.get(section, option, **kwds))

    def get_path(self, section: str, option: str, **kwds: Any) -> Path:
        return get_db_path(self.collection_path, self.get(section, option, **kwds))

    def get_multi_paths(self, section: str, option: str) -> list[Path]:
        if val := self[section].get(option):
            return [
                get_db_path(self.collection_path, name)
                for name in split_semicolon_list(val)
            ]
        return []

    def get_implicating_fields(
        self, tag_fields: Optional[list[str]] = None
    ) -> set[str]:
        if tag_fields is None:
            tag_fields = self.get_list("refresh", "TagFields")
        implicating_fields = set(tag_fields)
        if val := self["refresh"].get("ImplicatingFields"):
            arguments = frozenset(split_semicolon_list(val))
            if not arguments.issubset(implicating_fields):
                log.warning(
                    "in configuration ImplicatingFields is not a subset of TagFields"
                )
            implicating_fields &= arguments
        return implicating_fields


def acquire_db_config(collection_path: Path) -> Optional[DBConfig]:
    """
    If *collection_path* represents a valid collection, construct and return
    ``DBConfig`` for that collection's configuration, else return ``None``.
    """
    config_path = get_db_path(collection_path)
    if not config_path.is_file():
        log.error("No valid collection found at path: %s", config_path)
        return None
    parser = DBConfig(collection_path=collection_path)
    if not parser.read(config_path):
        log.error("Unable to read configuration from file: %s", config_path)
    log.debug("Using collection_path: %r", collection_path)
    return parser


def path_sc(cla: argparse.Namespace, config: GlobalConfig) -> int:
    """Path sub-command"""
    collection_path = config.find_collection(cla.collection)
    print(collection_path)
    return 0


def init_sc(cla: argparse.Namespace, global_config: GlobalConfig) -> int:
    """Init sub-command"""
    err_msg = "Unable to init"
    root = Path(cla.directory or cla.collection or Path.cwd())
    if not root.is_dir():
        log.error("%s: Not a directory: %s", err_msg, root)
        return 1
    # At a minimum, create an empty config
    db_dir = root / DB_DIR_NAME
    config_path = db_dir / DB_CONFIG_NAME
    # Don't overwrite
    if config_path.is_file():
        log.error(
            "%s: Refusing to overwrite existing configuration file: %s",
            err_msg,
            config_path,
        )
        return 1
    if cla.bare:
        db_dir.mkdir(exist_ok=True)
        log.info("Created directory: %s", db_dir)
        config_path.touch()
        log.info("Created empty configuration file: %s", config_path)
        return 0
    if template_dir := global_config.init.get("TemplateDir"):
        template_dir = Path(template_dir).expanduser()
        if not template_dir.is_dir():
            log.error("%s: TemplateDir is not a directory: %s", err_msg, template_dir)
            return 1
        shutil.copytree(template_dir, db_dir, copy_function=shutil.copy)
        log.info("Copied TemplateDir '%s' to new path '%s'", template_dir, db_dir)
        return 0
    if template_conf := global_config.init.get("TemplateConf"):
        template_conf = Path(template_conf).expanduser()
        if not template_conf.is_file():
            log.error("%s: TemplateConf is not a file: %s", err_msg, template_conf)
            return 1
        shutil.copy(template_conf, config_path)
        log.info(
            "Copied TemplateConf '%s' to new path '%s'", template_conf, config_path
        )
        return 0
    # Create default config
    db_dir.mkdir(exist_ok=True)
    log.info("Created directory: %s", db_dir)
    with open(config_path, "w", encoding="utf-8") as file:
        DBConfig(collection_path=root).write(file)
        log.info("Created default configuration file: %s", config_path)
    return 0


def traverse_sc(cla: argparse.Namespace, config: GlobalConfig) -> int:
    """Traverse sub-command"""
    collection_path = config.find_collection(cla.collection)
    db_config = acquire_db_config(collection_path)
    if not db_config:
        return 1
    filename = cla.output
    if not filename:
        filename = db_config.get_path("db", "CSVName")
        if not cla.force and filename.exists():
            log.error("Refusing to overwrite existing CSV file: %s", filename)
            return 1
    path_field = db_config.get("db", "PathField")
    count_field = db_config.get("db", "CountField")
    tag_fields = db_config.get_list("db", "TagFields")
    if filename != sys.stdout:
        try:
            output_file = open(filename, "w", encoding="utf-8", newline="")
        except OSError as err:
            log.error("Unable to open CSV file for writing: %s", err)
            return 1
        log.info("Writing CSV to file: %s", output_file.name)
    else:
        output_file = nullcontext(sys.stdout)
    with output_file as file:
        writer = csv.DictWriter(file, fieldnames=[path_field, count_field, *tag_fields])
        for path, count in refresh.traverse_fs(collection_path, leaves_only=cla.leaves):
            path_value = path.relative_to(collection_path)
            gallery = refresh.gms.Gallery({path_field: path_value, count_field: count})
            writer.writerow(gallery)
    return 0


def count_sc(cla: argparse.Namespace, config: GlobalConfig) -> int:
    """Count sub-command"""
    filename = cla.csvfile
    tag_fields = cla.fields
    if not cla.csvfile or not cla.fields:
        db_config = acquire_db_config(config.find_collection(cla.collection))
        if not db_config:
            return 1
        filename = filename or db_config.get_path("db", "CSVName")
        tag_fields = tag_fields or db_config.get_list("count", "TagFields")
    if filename != sys.stdin:
        try:
            input_file = open(filename, encoding="utf-8", newline="")
        except OSError as err:
            log.error("Unable to open CSV file for reading: %s", err)
            return 1
    else:
        input_file = nullcontext(sys.stdin)
    with input_file as file:
        reader = csv.DictReader(file)
        if cla.summarize:
            return tagcount.summarize(reader, tag_fields)
        return tagcount.count(reader, tag_fields, cla.reverse)


def query_sc(cla: argparse.Namespace, config: GlobalConfig) -> int:
    """Query sub-command"""
    filename = cla.csvfile
    tag_fields = cla.field
    fmt = table_query.auto_format(cla.format)
    field_fmts = {}
    if fmt or not filename:
        db_config = acquire_db_config(config.find_collection(cla.collection))
        if not db_config:
            return 1
        filename = filename or db_config.get_path("db", "CSVName")
        tag_fields = tag_fields or db_config.get_list("query", "TagFields")
        if cla.format is None:
            try:
                format_from_config = table_query.Format(
                    db_config.get("query", "Format").lower()
                )
            except ValueError as err:
                log.error("Invalid configuration setting: %s", err)
                return 1
            fmt = table_query.auto_format(format_from_config)
        if fmt:
            fmts_file = db_config.get_path("query", "FieldFormats")
            try:
                field_fmts = table_query.parse_field_format_file(fmts_file)
            except OSError as err:
                log.error("Unable to open FieldFormats file: %s", err)
                return 1
    if filename != sys.stdin:
        try:
            input_file = open(filename, encoding="utf-8", newline="")
        except OSError as err:
            log.error("Unable to open CSV file for reading: %s", err)
            return 1
    else:
        input_file = nullcontext(sys.stdin)
    with input_file as file:
        try:
            return table_query.main(
                csv.DictReader(file), cla.term, tag_fields, field_fmts
            )
        except BrokenPipeError:
            # Even though BrokenPipeError was caught, suppress the error
            # message by closing stderr before exiting.
            sys.stderr.close()
            return 0


def refresh_sc(cla: argparse.Namespace, config: GlobalConfig) -> int:
    """Refresh sub-command"""
    collection_path = config.find_collection(cla.collection)
    db_config = acquire_db_config(collection_path)
    if not db_config:
        return 1
    if cla.validate:
        return validate_tag_actions(db_config)
    gardener = refresh.Gardener()
    # First, acquire all "guaranteed" values.
    filename = db_config.get_path("db", "CSVName")
    tag_fields = db_config.get_list("refresh", "TagFields")
    gardener.set_normalize_tags(*tag_fields)
    backup_suffix = db_config.get("refresh", "BackupSuffix")
    # Second, acquire values for Update file count, if requested
    path_field = db_config.get("refresh", "PathField")
    count_field = db_config.get("refresh", "CountField")
    if not cla.no_check:
        gardener.set_update_count(path_field, count_field, collection_path)
    # Third, see if there are enough values to perform implication
    try:
        status = set_tag_actions(gardener, db_config)
    except OSError as err:
        log.error("Unable to open tag file for reading: %s", err)
        return 1
    if status != 0:
        return 1
    try:
        csvfile = open(filename, encoding="utf-8", newline="")
    except OSError as err:
        log.error("Unable to open CSV file for reading: %s", err)
        return 1
    with csvfile:
        reader = csv.DictReader(csvfile)
        fieldnames = reader.fieldnames
        if not fieldnames:
            return 0
        try:
            rows = list(gardener.garden_rows(reader, fieldnames=fieldnames))
        except KeyError as err:
            log.error("Field not in file: %s", err)
            return 1
        except OSError as err:
            log.error("With %s value: %s", path_field, err)
            return 1
    rows.sort(key=lambda row: util.alphanum_key(row[path_field].casefold()))
    backup_file = filename.replace(filename.with_name(filename.name + backup_suffix))
    log.info("Backed up '%s' -> '%s'", filename, backup_file)
    try:
        csvfile = open(filename, "w", encoding="utf-8", newline="")
    except OSError as err:
        log.error("Unable to open CSV file for writing: %s", err)
        return 1
    with csvfile:
        util.write_rows(rows=rows, fieldnames=fieldnames, file=csvfile)
    log.info("Success: Saved refreshed table to '%s'", filename)
    return 0


def validate_tag_actions(config: DBConfig) -> int:
    """Sub-function of ``refresh_sc``

    Validate the ``Implicator``s from any TagActions files.
    """
    unified = config.get_multi_paths("refresh", "TagActions")
    if not unified:
        log.info("No TagActions files to validate")
        return 0
    uof = refresh.UnifiedObjectFormat()
    for filename in unified:
        try:
            obj = refresh.get_unified(filename)
        except OSError as err:
            log.error("Unable to open TagActions file for reading: %s", err)
            return 1
        uof.update(obj)
    errors = 0
    for field, implic in uof.implicators():
        log.debug("Validating implicator for field(s): %s", field)
        # For alias error events, log all in debug output, but log only the
        # first example in error output.
        if ta_events := implic.validate_aliases_not_aliased():
            log.debug(ta_events)
            log.error(
                "Cannot alias a tag to a tag that is itself aliased: %s",
                " -> ".join(ta_events[0]),
            )
            log.error(
                "Found %d instance%s of transitive aliases",
                len(ta_events),
                "" if len(ta_events) == 1 else "s",
            )
            errors += len(ta_events)
        if ai_events := implic.validate_implications_not_aliased():
            log.debug(ai_events)
            log.error(
                "Tags in implication must not be aliased to another tag: "
                "'%s' implies '%s', but '%s' is aliased to '%s'",
                ai_events[0].implication.antecedent,
                ai_events[0].implication.consequent,
                ai_events[0].antecedent,
                ai_events[0].consequent,
            )
            log.error(
                "Found %d instance%s where tags in implication were aliased",
                len(ai_events),
                "" if len(ai_events) == 1 else "s",
            )
            errors += len(ai_events)
        if cycle := implic.find_cycle():
            log.error(
                "Tag implication cannot create a circular relation with "
                "another tag implication: %s",
                " -> ".join(cycle),
            )
            log.info("More circular relations may exist in the implication graph")
            errors += 1
    msg = "Found %d logical error%s in TagActions files: %s"
    paths = join_semicolon_list(config.get_list("refresh", "TagActions"))
    log.info(msg, errors, "" if errors == 1 else "s", paths)
    if errors != 0:
        return 1
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
    uof = refresh.UnifiedObjectFormat()
    for filename in unified:
        uof.update(refresh.get_unified(filename))
    for field, implic in uof.implicators():
        if field is None:
            gardener.set_implicator(implic, *implicating_fields)
        else:
            gardener.set_implicator(implic, field)
    return 0


def overlaps_sc(cla: argparse.Namespace, config: GlobalConfig) -> int:
    """Overlaps sub-command"""
    tag_fields = cla.fields
    input_file = cla.csvfile
    output_file = cla.output
    if not tag_fields or not input_file or not output_file:
        collection_path = config.find_collection(cla.collection)
        db_config = acquire_db_config(collection_path)
        if not db_config:
            return 1
        tag_fields = tag_fields or db_config.get_list("overlaps", "TagFields")
        output_dir = get_db_path(
            collection_path,
            "overlaps-" + relatedtag.get_field_directory_name(tag_fields),
        )
        if cla.clean:
            return relatedtag.clean_directory(output_dir)

        input_file = input_file or db_config.get_path("overlaps", "CSVName")
        if not output_file:
            output_dir.mkdir(exist_ok=True)
            output_file = relatedtag.get_new_json_filename(output_dir)

    input_file = None if input_file is sys.stdin else input_file
    output_file = None if output_file is sys.stdout else output_file
    return relatedtag.create_new_json_file(
        tag_fields, infile=input_file, outfile=output_file
    )


def freq_sc(cla: argparse.Namespace, config: GlobalConfig) -> int:
    """Freq sub-command"""
    input_file = cla.jsonfile
    limit = cla.limit
    if not input_file:
        collection_path = config.find_collection(cla.collection)
        db_config = acquire_db_config(collection_path)
        if not db_config:
            return 1
        tag_fields = cla.field or db_config.get_list("overlaps", "TagFields")
        json_dir = get_db_path(
            collection_path,
            "overlaps-" + relatedtag.get_field_directory_name(tag_fields),
        )
        input_file = relatedtag.get_current_json_filename(json_dir)
        if not input_file:
            log.error("JSON files not found in directory: %s", json_dir)
            return 1
        if limit is None:
            try:
                limit = db_config.getint("freq", "Limit")
            except ValueError as err:
                log.error("Invalid configuration setting for Limit: %s", err)
                return 1
    if input_file != sys.stdin:
        try:
            jsonfile = open(input_file, encoding="utf-8")
        except OSError as err:
            log.error("Unable to open JSON file for reading: %s", err)
            return 1
    else:
        jsonfile = nullcontext(sys.stdin)
    with jsonfile as file:
        try:
            table = relatedtag.load_from_json(file)
        except json.JSONDecodeError as err:
            log.error("Unable to decode JSON file: %s", err)
            log.debug(err.doc)
            return 1
        except (AttributeError, KeyError, TypeError):
            log.exception(
                "Unable to create overlap table from JSON file: %s", file.name
            )
            return 1
        log.info(
            "Table from %s contains %d 2-combinations of %d elements from %d sets",
            file.name,
            math.comb(len(table), 2),
            len(table),
            table.n_sets,
        )
    relatedtag.print_relatedtags(table, cla.tags, limit=limit)
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
    init_p.add_argument("--bare", action="store_true", help="create empty config file")
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
    count_p.add_argument("-r", "--reverse", action="store_true", help="sort ascending")
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
        description="Print galleries matching search term(s).",
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
    query_p.add_argument("term", metavar="TERM", nargs="*", help="term(s) of search")
    query_p.set_defaults(func=query_sc)

    refresh_p = subparsers.add_parser(
        "refresh",
        help="update the table",
        description="Update galleries' info, garden tags.",
    )
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

    overlaps_p = subparsers.add_parser(
        "overlaps",
        help="create table of tag relationships",
        description="Analyze co-occurrence of tags, create new overlap table.",
    )
    overlaps_p.add_argument(
        "-C",
        "--clean",
        action="store_true",
        help="remove overlap tables except the most recent",
    )
    overlaps_p.add_argument(
        "-i",
        "--input",
        metavar="FILE",
        dest="csvfile",
        type=FileType("r"),
        help="read CSV from %(metavar)s (use '-' for standard input)",
    )
    overlaps_p.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        type=FileType("w"),
        help="write overlap table to %(metavar)s (use '-' for standard output)",
    )
    overlaps_p.add_argument(
        "fields",
        nargs="*",
        metavar="FIELD",
        help="use %(metavar)s(s) instead of default TagFields",
    )
    overlaps_p.set_defaults(func=overlaps_sc)

    freq_p = subparsers.add_parser(
        "freq",
        help="list related tags",
        description="Print frequently co-occurring tags, reading previously-created overlap table.",
    )
    freq_p.add_argument(
        "tags", nargs="+", metavar="TAG", help="list tags similar to %(metavar)s(s)"
    )
    freq_p.add_argument(
        "-f",
        "--field",
        metavar="NAME",
        action="append",
        help="open the overlap table for field %(metavar)s(s) instead of default TagFields",
    )
    freq_p.add_argument(
        "-i",
        "--input",
        metavar="FILE",
        dest="jsonfile",
        type=FileType(),
        help="read overlap table from %(metavar)s (use '-' for standard input)",
    )
    freq_p.add_argument(
        "-l",
        "--limit",
        metavar="N",
        type=int,
        help="limit number of results per TAG to %(metavar)s (0 for no limit)",
    )
    freq_p.set_defaults(func=freq_sc)

    general_opts = top_level.add_argument_group(title="general options")
    general_opts.add_argument(
        "-h", "--help", action="help", help="show this help message and exit"
    )
    general_opts.add_argument(
        "-V", "--version", action="version", version=f"{__prog__} {__version__}"
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


def main() -> int:
    logging.basicConfig(
        level=logging.DEBUG, format=f"{__prog__}: %(levelname)s: %(message)s"
    )
    global_config = parse_global_config()
    args = build_cla_parser().parse_args()
    set_logging_level(args, global_config.verbose)
    log.debug(args)
    return args.func(args, global_config)


def set_logging_level(
    args: argparse.Namespace, config_setting: Optional[bool] = None
) -> None:
    verbosity = 0
    if config_setting is not None:
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
    return base_dir / __prog__


def get_db_path(collection_path: Path, filename: str = DB_CONFIG_NAME) -> Path:
    return collection_path / DB_DIR_NAME / filename


def parse_global_config(filename: str = "config") -> GlobalConfig:
    config_dir_path = get_global_config_dir()
    config_path = config_dir_path / filename
    parser = configparser.ConfigParser(
        interpolation=configparser.ExtendedInterpolation()
    )
    parser.read(config_path)
    global_config = GlobalConfig()
    if "collections" in parser:
        collections = parser["collections"]
        global_config.collections = {
            option: Path(value).expanduser() for option, value in collections.items()
        }
    if "global" in parser:
        global_section = parser["global"]
        global_config.default = global_section.get("Default")
        try:
            global_config.verbose = global_section.getboolean("Verbose", fallback=None)
        except ValueError as err:
            log.warning("Invalid global configuration setting for Verbose: %s", err)
    if "init" in parser:
        init_section = parser["init"]
        global_config.init.update(init_section)
    return global_config


def join_semicolon_list(items: Iterable[str]) -> str:
    return "; ".join(items)


def split_semicolon_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(";")]


if __name__ == "__main__":
    sys.exit(main())
