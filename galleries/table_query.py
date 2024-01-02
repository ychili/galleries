# table_query.py
#
"""Use the query functionality of galleryms to query the table data."""

from __future__ import annotations

import enum
import locale
import logging
import shlex
import shutil
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Optional, TextIO, TypeVar, Union

from . import galleryms as gms
from . import util

FormatT = TypeVar("FormatT", bound="Format")

log = logging.getLogger(__name__)


class SearchTermError(ValueError):
    pass


class Format(enum.Enum):
    NONE = "none"
    FORMAT = "format"
    AUTO = "auto"

    def __str__(self) -> str:
        return str(self.name).lower()

    def __repr__(self) -> str:
        return str(self)

    @classmethod
    def argparse(cls: type[FormatT], s: str) -> Union[FormatT, str]:
        try:
            return cls[s.upper()]
        except KeyError:
            return s


def auto_format(fmt: Format) -> bool:
    """Should output be formatted, according to *fmt*?"""
    return fmt == Format.FORMAT or fmt == Format.AUTO and sys.stdout.isatty()


def query_from_args(
    args: Iterable[str],
    fieldnames: Sequence[str],
    default_tag_fields: Optional[Iterable[str]] = None,
) -> gms.Query:
    parser = gms.ArgumentParser(default_tag_fields=default_tag_fields)
    try:
        query = parser.parse_args(args)
    except gms.ArgumentParsingError as err:
        log.error("Invalid search term: '%s'", err)
        raise SearchTermError(err) from err
    for search_term in query.all_terms():
        if not search_term.fields:
            log.error(
                "All search terms must have field specifiers "
                "if no --field argument(s) are provided: %s",
                search_term,
            )
            raise SearchTermError(search_term)
        try:
            search_term.disambiguate_fields(fieldnames=fieldnames)
        except gms.DisambiguationError as err:
            log.error("Cannot disambiguate field specifier: %s", err)
            raise SearchTermError(search_term) from err
    log.debug(query)
    return query


def main(
    galleries: Iterable[gms.Gallery],
    fieldnames: Sequence[str],
    field_formats: Optional[Mapping[str, gms.FieldFormat]] = None,
    sort_field: Optional[str] = None,
    reverse_sort: bool = False,
) -> int:
    if sort_field:
        if sort_field not in fieldnames:
            log.error("Sort field not found in input: %s", sort_field)
            return 1
        sort_key = util.alphanum_getter(sort_field)
    else:
        sort_key = None
    if field_formats:
        for field in field_formats:
            if field not in fieldnames:
                log.error(
                    "Field name from FieldFormats file not found in input: %s", field
                )
                return 1
        galleries = list(galleries)
        gallery_total = len(galleries)
        log.info(
            "Found %d galler%s", gallery_total, "y" if gallery_total == 1 else "ies"
        )
        if sort_key:
            galleries.sort(key=sort_key, reverse=reverse_sort)
        print_formatted(galleries, field_formats)
    else:
        if sort_key:
            galleries = sorted(galleries, key=sort_key, reverse=reverse_sort)
        util.write_galleries(galleries, fieldnames=fieldnames)
    return 0


def print_formatted(
    rows: Iterable[gms.Gallery],
    field_formats: Mapping[str, gms.FieldFormat],
    file: TextIO = sys.stdout,
) -> None:
    """Write *rows* to *file* in wrapped columns."""
    max_width = shutil.get_terminal_size().columns
    tabulator = gms.Tabulator(field_formats, total_width=max_width, right_margin=0)
    for line in tabulator.tabulate(rows):
        print(line, file=file)


def parse_field_format_file(filename: gms.StrPath) -> dict[str, gms.FieldFormat]:
    """Parse lines in *filename*. Only return lines successfully parsed."""
    text = Path(filename).read_text(encoding="utf-8")
    max_widths = {}
    for lineno, line in enumerate(text.splitlines(), start=1):
        args = shlex.split(line, comments=True)
        if not args:
            continue
        if len(args) < 2:
            log.error(
                "%s:%d: Fieldname argument %s without width argument",
                filename,
                lineno,
                args[0],
            )
            continue
        fieldname = args[0]
        if "REM" in args[1].upper():
            width = gms.FieldFormat.REMAINING_SPACE
        else:
            try:
                width = locale.atoi(args[1])
            except ValueError:
                log.error(
                    "%s:%d: Could not convert width argument %s to integer",
                    filename,
                    lineno,
                    args[1],
                )
                continue
        optionals = iter(args[2:])
        fg_color = next(optionals, "").lower()
        bg_color = next(optionals, "").lower()
        effect = next(optionals, "").lower()
        try:
            max_widths[fieldname] = gms.FieldFormat(width, fg_color, bg_color, effect)
        except KeyError as err:
            log.error("%s:%d: Bad color argument: %s", filename, lineno, err)
    return max_widths
