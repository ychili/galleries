# table_query.py
#
"""Use the query functionality of galleryms to query the table data."""

from __future__ import annotations

import abc
import enum
import locale
import logging
import shlex
import shutil
import string
from collections.abc import (
    Callable,
    Iterable,
    Iterator,
    Mapping,
    MutableMapping,
    Reversible,
    Sequence,
)
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

import rich.box
import rich.console
import rich.errors
import rich.table

from . import PROG
from . import galleryms as gms
from . import util

if TYPE_CHECKING:
    from _typeshed import StrPath, SupportsWrite
    from typing_extensions import Self

FieldSortSpec = tuple[gms.FieldKeyFunc[gms.Gallery], bool]
StrT = TypeVar("StrT", bound=str)


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
    TSV = "tsv"
    FORMAT = "format"
    RICH = "rich"
    AUTO = "auto"

    def __str__(self) -> str:
        return str(self.name).lower()

    def __repr__(self) -> str:
        return str(self)

    @classmethod
    def argparse(cls, s: StrT) -> Self | StrT:
        try:
            return cls[s.upper()]
        except KeyError:
            return s


class RowFormatter(string.Formatter):
    """A custom ``string.Formatter`` for formatting with row templates.

    >>> RowFormatter().format("He is an {type}", type="halibut")
    'He is an halibut'
    """

    # This get_field doesn't access attributes or items, just treating
    # field_name as a complete lookup key.
    def get_field(
        self, field_name: str, args: Sequence[Any], kwargs: Mapping[str, Any]
    ) -> tuple[Any, str]:
        obj = self.get_value(field_name, args, kwargs)
        return obj, field_name


class TablePrinter(abc.ABC):
    FORMAT_NAME: str
    STAR = "*"
    add_fields = True

    @abc.abstractmethod
    def print(self, galleries: Iterable[gms.Gallery]) -> None:
        pass

    _select_fields: Sequence[str]

    @property
    def fieldnames(self) -> Sequence[str]:
        """Field names currently selected."""
        return self._select_fields

    def order_fields(self, fieldnames: Sequence[str] | None) -> None:
        """Select fields *fieldnames* to display in output.

        If *fieldnames* is None, an empty sequence, or a sequence containing
        only the value ``STAR`` (by default, '*'), then selected ``fieldnames``
        will be replaced with an empty list.
        """
        if not fieldnames or self._is_star(fieldnames):
            self._select_fields = []
        else:
            self._select_fields = fieldnames

    def _is_star(self, fieldnames: object) -> bool:
        match fieldnames:
            case [self.STAR]:
                return True
        return False

    def check_fields(self, fieldnames: Sequence[str]) -> None:
        """
        Raise ``FormatterError`` if a requested field is not found in
        *fieldnames*.

        If ``fieldnames`` currently selected is empty, then it will be replaced
        with *fieldnames*.
        """
        if self.add_fields and not self._select_fields:
            self.order_fields(fieldnames)
        for field in self._select_fields:
            if field not in fieldnames:
                log.error(
                    "Field selected for output format '%s' not found in input: %s",
                    self.FORMAT_NAME,
                    field,
                )
                raise FormatterError(field)


class CSVTablePrinter(TablePrinter):
    """A TablePrinter that uses ``util.write_galleries``.

    >>> printer = CSVTablePrinter(select_fields=["*"])
    >>> printer.fieldnames
    []
    >>> printer.check_fields(["A"])
    >>> printer.fieldnames
    ['A']
    """

    FORMAT_NAME = "csv"

    def __init__(
        self, select_fields: Sequence[str] | None, file: StrPath | None = None
    ) -> None:
        self.order_fields(select_fields)
        self.file = file

    def print(self, galleries: Iterable[gms.Gallery]) -> None:
        util.write_galleries(galleries, self._select_fields, file=self.file)


class TSVTablePrinter(TablePrinter):
    FORMAT_NAME = "tsv"

    def __init__(
        self,
        select_fields: Sequence[str] | None,
        file: SupportsWrite[str] | None = None,
    ) -> None:
        self.order_fields(select_fields)
        self.file = file

    def print(self, galleries: Iterable[gms.Gallery]) -> None:
        header = "\t".join(self._select_fields)
        print(header, file=self.file)
        for gallery in galleries:
            row = "\t".join(
                str(gallery[fieldname]) for fieldname in self._select_fields
            )
            print(row, file=self.file)


class FormattedTablePrinter(TablePrinter):
    """A TablePrinter that uses ``print_formatted``."""

    FORMAT_NAME = "format"

    def __init__(
        self,
        field_formats: dict[str, gms.FieldFormat],
        select_fields: Sequence[str] | None = None,
        file: SupportsWrite[str] | None = None,
    ) -> None:
        self.field_formats = field_formats
        self.order_fields(select_fields)
        self.file = file

    def selected_field_formats(self) -> dict[str, gms.FieldFormat]:
        field_formats = {
            field: self.field_formats.get(
                field, gms.FieldFormat(gms.FieldFormat.REMAINING_SPACE)
            )
            for field in self._select_fields
        }
        fields_with_default_ff = field_formats.keys() - self.field_formats
        if fields_with_default_ff:
            log.debug(
                "Constructed default FieldFormats for fields selected but not defined:"
                " %r",
                sorted(fields_with_default_ff),
            )
        return field_formats

    def print(self, galleries: Iterable[gms.Gallery]) -> None:
        print_formatted(galleries, self.selected_field_formats(), self.file)


class RichTablePrinter(TablePrinter):
    """A TablePrinter that uses a ``rich.table.Table``."""

    FORMAT_NAME = "rich"

    def __init__(
        self,
        table_kwds: Mapping[str, Any] | None = None,
        field_columns: MutableMapping[str, rich.table.Column] | None = None,
        select_fields: Sequence[str] | None = None,
        console: rich.console.Console | None = None,
    ) -> None:
        self.table_kwds = table_kwds if table_kwds is not None else {}
        self.field_columns = field_columns if field_columns is not None else {}
        self.order_fields(select_fields)
        self.console = console or util.console

    def selected_columns(self) -> Iterator[rich.table.Column]:
        for field in self._select_fields:
            yield self.field_columns.get(field, rich.table.Column(header=field))

    def print(self, galleries: Iterable[gms.Gallery]) -> None:
        table = rich.table.Table(*self.selected_columns(), **self.table_kwds)
        for gallery in galleries:
            row = [str(gallery[fieldname]) for fieldname in self._select_fields]
            table.add_row(*row)
        try:
            self.console.print(table)
        except (
            TypeError,
            AttributeError,
            rich.errors.NotRenderableError,
            rich.errors.MissingStyle,
        ) as err:
            # These exceptions may/will be generated by invalid arguments to
            # Column at this point.
            log.error("Unable to render table: %s", err)
            raise FormatterError from err


class RowTemplatePrinter(TablePrinter):
    """A TablePrinter that uses ``RowFormatter``.

    >>> printer = RowTemplatePrinter("{Path:#>15}\\n")
    >>> printer.fieldnames
    ['Path']
    >>> printer.print([{"Path": "Hash Me"}])
    ########Hash Me
    """

    FORMAT_NAME = "rowtemplate"
    add_fields = False

    def __init__(
        self, format_string: str, file: SupportsWrite[str] | None = None
    ) -> None:
        self.format_string = format_string
        self.formatter = RowFormatter()
        self.order_fields(None)
        self.file = file

    def print(self, galleries: Iterable[gms.Gallery]) -> None:
        for gallery in galleries:
            try:
                row = self.formatter.vformat(self.format_string, (), gallery)
            except ValueError as err:
                log.error("Error with row template '%s': %s", self.format_string, err)
                raise FormatterError from err
            print(row, end="", file=self.file)

    def order_fields(self, fieldnames: Any) -> None:
        self._select_fields = [
            field_name
            for _, field_name, _, _ in self.formatter.parse(self.format_string)
            if field_name is not None
        ]


def query_from_args(
    args: Iterable[str],
    fieldnames: Sequence[str],
    default_tag_fields: Iterable[str] | None = None,
) -> gms.ConjunctiveSearchGroup:
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
    sort_specs: Sequence[FieldSortSpec] | None = None,
    *,
    reverse_order: bool = False,
) -> Iterable[gms.Gallery]:
    """Return *galleries* sorted by *sort_specs* if given, otherwise unsorted.

    Raise ``SortingError`` if a fieldname in *sort_specs* is not found in
    *fieldnames*.

    If *reverse_order* is True, *galleries* will be returned in reverse order,
    after any sorting.
    """
    if sort_specs:
        sort_fields = {field for spec, _ in sort_specs for field in spec.fields}
        if missing_fields := sort_fields - set(fieldnames):
            log.error("Sort field(s) not found in input: %s", ", ".join(missing_fields))
            raise SortingError(missing_fields)
        galleries = util.sort_by_field(galleries, sort_specs)
    if reverse_order:
        if not isinstance(galleries, Reversible):
            galleries = list(galleries)
        return reversed(galleries)
    return galleries


def print_table(
    galleries: Iterable[gms.Gallery],
    fieldnames: Sequence[str],
    output_formatter: TablePrinter | None = None,
) -> None:
    if not output_formatter:
        return util.write_galleries(galleries, fieldnames=fieldnames)
    output_formatter.check_fields(fieldnames)
    galleries = _lazy_total(galleries)
    output_formatter.print(galleries)


def _lazy_total(galleries: Iterable[gms.Gallery]) -> Iterator[gms.Gallery]:
    gallery_total = 0
    for gallery in galleries:
        gallery_total += 1
        yield gallery
    log.info("Found %d galler%s", gallery_total, "y" if gallery_total == 1 else "ies")


def print_formatted(
    rows: Iterable[gms.Gallery],
    field_formats: Mapping[str, gms.FieldFormat],
    file: SupportsWrite[str] | None = None,
) -> None:
    """Write *rows* to *file* in wrapped columns."""
    max_width = shutil.get_terminal_size().columns
    tabulator = gms.Tabulator(field_formats, total_width=max_width, right_margin=0)
    for line in tabulator.tabulate(rows):
        print(line, file=file)


def parse_field_format_file(filename: StrPath) -> dict[str, gms.FieldFormat]:
    """Parse lines in *filename*. Only return lines successfully parsed."""
    text = Path(filename).read_text(encoding="utf-8")
    max_widths = {}
    for lineno, line in enumerate(text.splitlines(), start=1):
        try:
            instruction = _field_format_from_text(line)
        except ValueError as err:
            log.error("%s:%d: %s", filename, lineno, err)
            continue
        if not instruction:
            continue
        fieldname, field_format = instruction
        max_widths[fieldname] = field_format
    return max_widths


def _field_format_from_text(line: str) -> tuple[str, gms.FieldFormat] | None:
    args = shlex.split(line, comments=True)
    if not args:
        return None
    if len(args) < 2:
        raise ValueError(f"Fieldname argument {args[0]} without width argument")
    fieldname = args[0]
    if "REM" in args[1].upper():
        width = gms.FieldFormat.REMAINING_SPACE
    else:
        try:
            width = locale.atoi(args[1])
        except ValueError as err:
            msg = f"Could not convert width argument {args[1]} to integer"
            raise ValueError(msg) from err
    optionals = iter(args[2:])
    fg_color = next(optionals, "").lower()
    bg_color = next(optionals, "").lower()
    effect = next(optionals, "").lower()
    try:
        return (
            fieldname,
            gms.FieldFormat.from_names(width, fg_color, bg_color, effect),
        )
    except KeyError as err:
        raise ValueError(f"Bad color argument: {err}") from err


def parse_rich_table_file(filename: StrPath) -> RichTablePrinter:
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
    return parse_rich_table_object(data, source=str(path))


def parse_rich_table_object(
    data: object, source: str | None = None
) -> RichTablePrinter:
    """Extract Rich table settings from parsed object *data*."""
    extr = util.ObjectExtractor(source=source)
    obj = extr.dict(data)
    if not obj:
        extr.warn("No data!")
        return _default_rich_table()
    with extr.get_dict(obj, "table") as table_def:
        table_kwds = _parse_table_settings(extr, table_def)
    column_def = extr.get_list(obj, "columns")
    field_columns: dict[str, rich.table.Column] = {}
    for ind, decl in enumerate(column_def, start=1):
        _parse_column_settings(
            decl,
            field_columns,
            lambda *args: extr.warn(
                ": ".join(map(str, [f"At column def {ind}", *args]))  # noqa: B023
            ),
        )
    if not field_columns:
        return _default_rich_table(table_kwds)
    return RichTablePrinter(table_kwds, field_columns)


def _default_rich_table(
    table_kwds: Mapping[str, Any] | None = None,
) -> RichTablePrinter:
    if table_kwds is None:
        table_kwds = {"box": DEFAULT_BOX}
    return RichTablePrinter(table_kwds, field_columns=None)


def _parse_table_settings(
    extr: util.ObjectExtractor, table_def: Mapping
) -> dict[str, Any]:
    table_kwds: dict[str, Any] = {"box": DEFAULT_BOX}
    with extr.get(table_def, "box", util.Const.sentinel) as arg:
        match arg:
            case None | False:
                table_kwds["box"] = None
            case str() if (box := getattr(rich.box, arg, None)) and isinstance(
                box, rich.box.Box
            ):
                table_kwds["box"] = box
            case util.Const.sentinel | True:
                pass
            case _:
                extr.warn("Not a known Box style (defaulting): %s", arg)
    with extr.get(table_def, "show_header", None) as arg:
        match arg:
            case bool():
                table_kwds["show_header"] = arg
            case None:
                pass
            case _:
                extr.warn("Invalid value for show_header (defaulting): %s", arg)
    return table_kwds


def _parse_column_settings(
    decl: object,
    field_columns: MutableMapping[str, rich.table.Column],
    warn: Callable[..., None],
) -> None:
    match decl:
        case {"field": field, **kwargs}:
            field = str(field)
            if kwargs:
                kwargs.setdefault("header", field)
                try:
                    column = rich.table.Column(**kwargs)
                except (TypeError, rich.errors.StyleError) as err:
                    warn(f"Error with parameter for field {field}", err)
                    return
            else:
                column = rich.table.Column(header=field)
            field_columns[field] = column
        case {}:
            warn('Required key "field" is missing', decl)
        case _:
            warn("Item is wrong type (should be object/table)", decl)
