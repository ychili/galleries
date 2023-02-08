# table_query.py
#
"""Use the query functionality of galleryms to query the table data."""

from __future__ import annotations

import csv
import locale
import logging
import shlex
import shutil
import sys
from enum import Enum
from pathlib import Path
from typing import Iterable, TextIO, TypeVar, Union

from . import galleryms as gms
from . import util

FmtType = TypeVar("FmtType", bound="Format")

log = logging.getLogger(__name__)


class Format(Enum):
    NONE = "none"
    FORMAT = "format"
    AUTO = "auto"

    def __str__(self) -> str:
        return str(self.name).lower()

    def __repr__(self) -> str:
        return str(self)

    @classmethod
    def argparse(cls: type[FmtType], s: str) -> Union[FmtType, str]:
        try:
            return cls[s.upper()]
        except KeyError:
            return s


def auto_format(enum: Format) -> bool:
    """Should output be formatted, according to *enum*?"""
    return enum == Format.FORMAT or enum == Format.AUTO and sys.stdout.isatty()


def main(
    reader: csv.DictReader,
    args: list[str],
    tag_fields: list[str],
    field_formats: dict[str, gms.FieldFormat],
) -> int:
    parser = gms.ArgumentParser(default_tag_fields=tag_fields)
    try:
        query = parser.parse_args(args)
    except ValueError as err:
        log.error("Invalid search term: '%s'", err)
        return 1
    fieldnames = reader.fieldnames
    if not fieldnames:
        return 0
    for search_term in query.all_terms():
        if not search_term.fields:
            log.error(
                "All search terms must have field specifiers "
                "if no --field argument(s) are provided: %s",
                search_term,
            )
            return 1
        try:
            search_term.disambiguate_fields(fieldnames=fieldnames)
        except ValueError as err:
            log.error("Cannot disambiguate field specifier: %s", err)
            return 1
    log.debug(query)
    matched_rows = (
        gallery for row in reader if query.match(gallery := gms.Gallery(row))
    )

    if field_formats:
        for field in field_formats:
            if field not in fieldnames:
                log.error(
                    "Field name from FieldFormats file not found in input: %s", field
                )
                return 1
        galleries = list(matched_rows)
        gallery_total = len(galleries)
        log.info(
            "Found %d galler%s", gallery_total, "y" if gallery_total == 1 else "ies"
        )
        print_formatted(galleries, field_formats)
    else:
        util.write_rows(matched_rows, fieldnames=fieldnames)
    return 0


def print_formatted(
    rows: Iterable[gms.Gallery],
    field_formats: dict[str, gms.FieldFormat],
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
