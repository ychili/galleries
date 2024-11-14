# table_query.py
#
"""Use the query functionality of galleryms to query the table data."""

from __future__ import annotations

import abc
import enum
import locale
import logging
import os
import shlex
import shutil
import sys
from collections.abc import Collection, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, TextIO, TypeVar

import rich.box
import rich.console
import rich.errors
import rich.table

from . import PROG
from . import galleryms as gms
from . import util

FormatT = TypeVar("FormatT", bound="Format")

DEFAULT_BOX = rich.box.SIMPLE

log = logging.getLogger(PROG)


ArgumentParser = gms.ArgumentParser


class TableQueryError(ValueError):
    pass


class SearchTermError(TableQueryError):
    pass


class SortingError(TableQueryError):
    pass


class FormatterError(TableQueryError):
    pass


class Format(enum.Enum):
    NONE = "none"
    FORMAT = "format"
    RICH = "rich"
    AUTO = "auto"

    def __str__(self) -> str:
        return str(self.name).lower()

    def __repr__(self) -> str:
        return str(self)

    @classmethod
    def argparse(cls: type[FormatT], s: str) -> FormatT | str:
        try:
            return cls[s.upper()]
        except KeyError:
            return s


class TablePrinter(abc.ABC):
    @abc.abstractmethod
    def print(self, galleries: Iterable[gms.Gallery]) -> None:
        pass

    @abc.abstractmethod
    def check_fields(self, fieldnames: Collection[str]) -> None:
        """
        Raise ``FormatterError`` if a requested field is not found in
        *fieldnames*.
        """


class FormattedTablePrinter(TablePrinter):
    """A TablePrinter that uses ``print_formatted``."""

    def __init__(
        self,
        field_formats: dict[str, gms.FieldFormat],
        file: TextIO | None = sys.stdout,
    ) -> None:
        self.field_formats = field_formats
        self.file = file

    def print(self, galleries: Iterable[gms.Gallery]) -> None:
        print_formatted(galleries, self.field_formats)

    def check_fields(self, fieldnames: Collection[str]) -> None:
        for field in self.field_formats:
            if field not in fieldnames:
                log.error(
                    "Field name from FieldFormats file not found in input: %s", field
                )
                raise FormatterError(field)


class RichTablePrinter(TablePrinter):
    """A TablePrinter that uses a ``rich.table.Table``.

    If *add_fields* is True (the default) and *fieldnames* is not given,
    then ``check_fields`` will update fieldnames from its
    *fieldnames* argument.
    """

    def __init__(
        self,
        table: rich.table.Table,
        fieldnames: Sequence[str] | None = None,
        console: rich.console.Console | None = None,
        *,
        add_fields: bool = True,
    ) -> None:
        self.table = table
        self.fieldnames = fieldnames or []
        self.console = console or util.console
        self.add_fields = add_fields

    def print(self, galleries: Iterable[gms.Gallery]) -> None:
        for gallery in galleries:
            row = [str(gallery[fieldname]) for fieldname in self.fieldnames]
            self.table.add_row(*row)
        try:
            self.console.print(self.table)
        except (TypeError, AttributeError, rich.errors.NotRenderableError) as err:
            log.error("Unable to render table: %s", err)
            raise FormatterError from err

    def check_fields(self, fieldnames: Collection[str]) -> None:
        if self.add_fields and not self.fieldnames:
            self.fieldnames = list(fieldnames)
            for field in fieldnames:
                self.table.add_column(header=field)
        for field in self.fieldnames:
            if field not in fieldnames:
                log.error(
                    "Field name from RichTable file not found in input: %s", field
                )
                raise FormatterError(field)


def query_from_args(
    args: Iterable[str],
    fieldnames: Sequence[str],
    default_tag_fields: Iterable[str] | None = None,
) -> gms.Query:
    parser = ArgumentParser(default_tag_fields=default_tag_fields)
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


def sort_table(
    galleries: Iterable[gms.Gallery],
    fieldnames: Sequence[str],
    sort_field: str | None = None,
    *,
    reverse_sort: bool = False,
) -> Iterable[gms.Gallery]:
    """Return *galleries* sorted by *sort_field* if given, otherwise unsorted.

    Raise ``SortingError`` if *sort_field* is not found in *fieldnames*.
    """
    if sort_field:
        if sort_field not in fieldnames:
            log.error("Sort field not found in input: %s", sort_field)
            raise SortingError(sort_field)
        return util.sort_by_field(galleries, sort_field, reverse=reverse_sort)
    return galleries


def print_table(
    galleries: Iterable[gms.Gallery],
    fieldnames: Sequence[str],
    output_formatter: TablePrinter | None = None,
) -> None:
    if output_formatter:
        output_formatter.check_fields(fieldnames)
        galleries = list(galleries)
        gallery_total = len(galleries)
        log.info(
            "Found %d galler%s", gallery_total, "y" if gallery_total == 1 else "ies"
        )
        output_formatter.print(galleries)
    else:
        util.write_galleries(galleries, fieldnames=fieldnames)


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


def parse_rich_table_file(filename: gms.StrPath) -> RichTablePrinter:
    """Read *filename* and parse Rich table settings.

    ``*.toml`` files will be parsed as TOML. Anything else will be parsed
    as JSON.
    """
    path = Path(filename)
    load = util.load_from_json
    if path.match("*.toml"):
        load = util.load_from_toml
    try:
        data = load(path)
    except OSError:
        log.debug("can't read file with path %s, using default", path)
        return _default_rich_table()
    return parse_rich_table_object(data, source=path)


def parse_rich_table_object(
    data: object, source: os.PathLike | None = None
) -> RichTablePrinter:
    """Extract Rich table settings from parsed object *data*."""
    extr = util.ObjectExtractor(source=source)
    obj = extr.dict(data)
    if not obj:
        extr.warn("No data!")
        return _default_rich_table()
    with extr.get_dict(obj, "table") as table_def:
        table_kwds = _parse_table_settings(extr, table_def)
    table = rich.table.Table(**table_kwds)
    column_def = extr.get_list(obj, "columns")
    warning_tmpl = "At column def {}: {}: {}"
    columns: list[str] = []
    for ind, decl in enumerate(column_def, start=1):
        match decl:
            case {"field": field, **kwargs}:
                field = str(field)
                if kwargs:
                    kwargs.setdefault("header", field)
                    try:
                        table.add_column(**kwargs)
                    except (TypeError, rich.errors.StyleError) as err:
                        extr.warn(
                            warning_tmpl.format(
                                ind, f"Error with parameter for field {field}", err
                            )
                        )
                        continue
                else:
                    table.add_column(header=field)
                columns.append(field)
            case {}:
                extr.warn(
                    warning_tmpl.format(ind, 'Required key "field" is missing', decl)
                )
            case _:
                extr.warn(
                    warning_tmpl.format(
                        ind, "Item is wrong type (should be object/table)", decl
                    )
                )
    if not columns:
        return _default_rich_table(table=table)
    return RichTablePrinter(table, fieldnames=columns)


def _default_rich_table(table: rich.table.Table | None = None) -> RichTablePrinter:
    if table is None:
        table = rich.table.Table(box=DEFAULT_BOX)
    return RichTablePrinter(table, fieldnames=[])


def _parse_table_settings(
    extr: util.ObjectExtractor, table_def: Mapping
) -> dict[str, Any]:
    table_kwds: dict[str, Any] = {"box": DEFAULT_BOX}
    missing = object()
    with extr.get(table_def, "box", missing) as arg:
        if arg is None:
            table_kwds["box"] = None
        elif (box := getattr(rich.box, str(arg), None)) and isinstance(
            box, rich.box.Box
        ):
            table_kwds["box"] = box
        elif arg is not missing:
            extr.warn("Not a known Box style (defaulting): %s", arg)
    return table_kwds
