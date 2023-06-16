# relatedtag.py
#
"""Analyze related tags"""

from __future__ import annotations

import csv
import dataclasses
import logging
import math
import operator
import sys
from collections.abc import Collection, Iterable, Mapping, MutableMapping
from typing import IO, Any, Optional

from .galleryms import (
    FieldFormat,
    OverlapTable,
    SimilarityCalculator,
    Tabulator,
    TagSet,
    most_common,
)

log = logging.getLogger(__name__)


class ResultsTable:
    def __init__(
        self,
        file: IO,
        tabulator: Optional[Tabulator] = None,
        header: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self.file = file
        self.tabulator = tabulator or Tabulator({})
        self.header: Mapping[str, Any] = header or {}
        self.formats: dict[str, str] = {}

    def add_column(
        self, name: str, field_fmt: FieldFormat, format_spec: Optional[str] = None
    ) -> None:
        self.tabulator.field_fmts[name] = field_fmt
        if format_spec is not None:
            self.formats[name] = format_spec

    def write_formatted(
        self,
        data: Iterable[MutableMapping[str, Any]],
        header: Optional[Mapping[str, Any]] = None,
    ) -> None:
        rows: list[Mapping[str, Any]] = []
        if header is not None:
            rows.append(header)
        elif self.header:
            rows.append(self.header)
        for row in data:
            for key in row:
                if format_spec := self.formats.get(key):
                    row[key] = format(row[key], format_spec)
            rows.append(row)
        for line in self.tabulator.tabulate(rows):
            print(line, file=self.file)

    def write_blank(self) -> None:
        print(file=self.file)

    def write_csv(
        self,
        data: Iterable[Mapping[str, Any]],
        fieldnames: Collection[str],
        write_header: bool = True,
    ) -> None:
        writer = csv.DictWriter(self.file, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerows(data)


@dataclasses.dataclass(frozen=True)
class SimilarityResult:
    tag: str
    count: int
    cosine: float
    jaccard: float
    overlap: float
    frequency: float

    @classmethod
    def choices(cls) -> list[str]:
        return [field.name for field in dataclasses.fields(cls)]


def make_row(sim: SimilarityCalculator) -> SimilarityResult:
    return SimilarityResult(
        tag=sim.tag_b.tag,
        count=sim.tag_b.count,
        cosine=sim.cosine_similarity(),
        jaccard=sim.jaccard_index(),
        overlap=sim.overlap_coefficient(),
        frequency=sim.frequency(),
    )


def sort(
    calculators: Iterable[SimilarityCalculator], sort_by: str, n: Optional[int] = None
) -> list[SimilarityResult]:
    result_rows = (make_row(sim) for sim in calculators)
    return most_common(result_rows, n=n, key=operator.attrgetter(sort_by))


def query(
    table: OverlapTable, tag: str, sort_by: str, limit: Optional[int] = None
) -> list[SimilarityResult]:
    """Get similiarity results for *tag* from *table*."""
    try:
        return sort(table.similarities(tag), sort_by=sort_by, n=limit)
    except KeyError:
        nan = float("NaN")
        return [
            SimilarityResult(
                tag=tag, count=0, cosine=nan, jaccard=nan, overlap=nan, frequency=nan
            )
        ]


def overlap_table(tag_sets: Iterable[TagSet]) -> OverlapTable:
    table = OverlapTable(*tag_sets)
    if table:
        log.info(
            "Counted overlaps of %d 2-combinations of %d elements in %d sets "
            "(average %.2f elements per set)",
            math.comb(len(table), 2),
            len(table),
            table.n_sets,
            table.counter.total() / table.n_sets,
        )
    else:
        log.info("No elements counted!")
    return table


def results_table(file: IO, effect: bool = False) -> ResultsTable:
    """Return the ``ResultsTable`` with default settings."""
    printer = ResultsTable(file)
    printer.header = {
        field.name: field.name.upper() for field in dataclasses.fields(SimilarityResult)
    }
    printer.header["frequency"] = "FREQ"  # shorten
    floatfmt = (FieldFormat(7), ">7.5f")
    printer.add_column(
        "tag", FieldFormat(FieldFormat.REM, effect="bold" if effect else "")
    )
    printer.add_column("count", FieldFormat(5), ">5d")
    printer.add_column("cosine", *floatfmt)
    printer.add_column("jaccard", *floatfmt)
    printer.add_column("overlap", *floatfmt)
    printer.add_column("frequency", FieldFormat(4), ">4.0%")
    return printer


def print_relatedtags(
    data_table: OverlapTable,
    tag_names: Iterable[str],
    sort_by: str = "cosine",
    limit: Optional[int] = None,
    file: Optional[IO] = None,
    printer: Optional[ResultsTable] = None,
) -> None:
    if file is None:
        file = sys.stdout
    if printer is None:
        # Disable text effects if output is not a terminal
        # (e.g. a file or pipe)
        printer = results_table(file, effect=file.isatty())
    log.debug("sorting results by: %s", sort_by)
    tag_names = list(tag_names)
    tags_remaining = len(tag_names)
    for tag in tag_names:
        results = [
            dataclasses.asdict(result)
            for result in query(data_table, tag, sort_by=sort_by, limit=limit)
        ]
        printer.write_formatted(results)
        tags_remaining -= 1
        if tags_remaining:
            printer.write_blank()
