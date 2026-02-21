"""Command-line interface"""

from __future__ import annotations

import argparse
import configparser
import logging
from collections.abc import Sequence

from .. import PROG, __version__, relatedtag, table_query
from . import ops
from .lib import DB_CONFIG_NAME as DB_CONFIG_NAME
from .lib import DB_DIR_NAME as DB_DIR_NAME
from .lib import FileType, read_global_configuration, set_logging_level

log = logging.getLogger(PROG)


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
    except configparser.Error as err:
        log.debug(
            "A configparser.Error is causing cli.main to exit with error: %s", err
        )
        return 1


def build_cla_parser() -> argparse.ArgumentParser:
    """Build and return command-line argument parser."""
    top_level = argparse.ArgumentParser(add_help=False)
    top_level.set_defaults(func=ops.path_sc)
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
    init_p.set_defaults(func=ops.init_sc)

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
    traverse_p.set_defaults(func=ops.traverse_sc)

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
    count_p.set_defaults(func=ops.count_sc)

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
    query_p.set_defaults(func=ops.query_sc)

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
    refresh_p.set_defaults(func=ops.refresh_sc)

    related_p = subparsers.add_parser(
        "related",
        help="list related tags",
        description="Print tags frequently occuring in galleries matching TERM(s)",
    )
    related_p.add_argument("term", metavar="TERM", nargs="*", help="term(s) of search")
    related_p.add_argument(
        "-f",
        "--field",
        metavar="NAME",
        action="append",
        help="show tags from %(metavar)s(s) instead of default TagFields",
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
    related_p.set_defaults(func=ops.related_sc)

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
