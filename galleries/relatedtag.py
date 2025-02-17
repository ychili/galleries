# relatedtag.py
#
"""Analyze related tags"""

from __future__ import annotations

import collections
import dataclasses
import logging
import operator
from collections.abc import Hashable, Iterable, Iterator, Mapping
from typing import Any, Generic, TypeVar

import rich.console
import rich.table

from . import PROG, util
from .galleryms import Gallery, Query, RelatedTag, TagCount, most_common

log = logging.getLogger(PROG)

T = TypeVar("T")
H = TypeVar("H", bound=Hashable)

_INT_SPEC = {"header": str.upper, "justify": "right"}
_FLOAT_SPEC = {"header": str.upper, "justify": "right", "formatspec": ".5f"}
TABLE_COLUMN_SETTINGS = {
    "tag": {"header": str.upper, "style": "bold"},
    "total": _INT_SPEC,
    "count": _INT_SPEC,
    "cosine": _FLOAT_SPEC,
    "jaccard": _FLOAT_SPEC,
    "overlap": _FLOAT_SPEC,
    "frequency": {
        "header": lambda name: str(name).upper()[:4],
        "justify": "right",
        "formatspec": ".0%",
    },
}


class ResultsTable(Generic[H]):
    """A wrapper for a ``rich.table.Table``"""

    def __init__(self, table: rich.table.Table | None = None) -> None:
        self.columns: list[H] = []
        self.formats: dict[H, str] = {}
        self.table = rich.table.Table() if table is None else table

    def add_column(self, fieldname: H, *, format_spec: str = "", **kwargs: Any) -> None:
        """Add a column to the table.

        *format_spec* will be used to ``format`` the value before printing.
        All other keyword arguments *kwargs* will be passed to
        ``Table.add_column``.
        """
        self.columns.append(fieldname)
        if format_spec:
            self.formats[fieldname] = format_spec
        self.table.add_column(**kwargs)

    def add_row(self, row: Mapping[H, object]) -> None:
        """Add a row to the table."""
        renderables: list[str] = []
        for column in self.columns:
            row_value = row[column]
            renderables.append(format(row_value, self.formats.get(column, "")))
        self.table.add_row(*renderables)


@dataclasses.dataclass(frozen=True)
class SimilarityResult(Generic[T]):
    tag: T
    total: int
    count: int
    cosine: float
    jaccard: float
    overlap: float
    frequency: float

    @classmethod
    def choices(cls) -> list[str]:
        return [field.name for field in dataclasses.fields(cls)]


def make_row(tag: RelatedTag[T]) -> SimilarityResult[T]:
    return SimilarityResult(
        tag=tag.tag.tag,
        total=tag.tag.count,
        count=tag.overlap_count,
        cosine=tag.cosine_similarity(),
        jaccard=tag.jaccard_index(),
        overlap=tag.overlap_coefficient(),
        frequency=tag.frequency(),
    )


def sort(
    tags: Iterable[RelatedTag[T]], sort_by: str, n: int | None = None
) -> list[SimilarityResult[T]]:
    result_rows = [make_row(related_tag) for related_tag in tags]
    log.debug("sorting results by: %s", sort_by)
    return most_common(result_rows, n=n, key=operator.attrgetter(sort_by))


def get_related_tags(
    galleries: Iterable[Gallery], query: Query, tag_fields: Iterable[str]
) -> Iterator[RelatedTag[str]]:
    """Yield tags in *tag_fields* from *galleries* matched by *query*."""
    # Counter for tags in tag_fields from all galleries
    total_tag_counter: collections.Counter[str] = collections.Counter()
    # Counter for tags in tag_fields from galleries matched by query
    related_tag_counter: collections.Counter[str] = collections.Counter()
    # Count of galleries matched by query
    search_count = 0
    for gallery in galleries:
        tag_set = gallery.merge_tags(*tag_fields)
        total_tag_counter.update(tag_set)
        if query.match(gallery):
            related_tag_counter.update(tag_set)
            search_count += 1
    for tag, overlap_count in related_tag_counter.items():
        yield RelatedTag(
            TagCount(tag, total_tag_counter[tag]),
            query=query,
            overlap_count=overlap_count,
            search_count=search_count,
        )


def results_table(
    field_settings: Iterable[tuple[str, Mapping[str, Any]]] | None = None
) -> ResultsTable[str]:
    """Return the ``ResultsTable`` using *field_settings*.

    The default is to use ``TABLE_COLUMN_SETTINGS``.
    """
    if field_settings is None:
        field_settings = TABLE_COLUMN_SETTINGS.items()
    printer: ResultsTable[str] = ResultsTable(table=rich.table.Table(box=None))
    for fieldname, settings in field_settings:
        settings = dict(settings)  # Copy before mutating.
        header = settings.pop("header", str)(fieldname)
        formatspec = settings.pop("formatspec", None)
        printer.add_column(fieldname, format_spec=formatspec, header=header, **settings)
    return printer


def print_results(
    related_tags: Iterable[SimilarityResult],
    console: rich.console.Console = util.console,
) -> None:
    printer = results_table()
    for result in related_tags:
        printer.add_row(dataclasses.asdict(result))
    console.print(printer.table)
