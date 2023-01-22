# relatedtag.py
#
"""Analyze related tags"""

from __future__ import annotations

import collections
import csv
import json
import logging
import math
import os
import sys
import time
from collections.abc import Sequence
from contextlib import nullcontext
from pathlib import Path
from typing import IO, Optional

from .galleryms import FieldFormat, OverlapTable, StrPath, Tabulator, most_common
from .util import check_field_names, tagsets_from_rows

log = logging.getLogger(__name__)


def load_from_json(file_object: IO) -> OverlapTable:
    """Recreate an ``OverlapTable`` previously serialized to JSON format."""
    return OverlapTable.from_json(json.load(file_object))


def create_new_json_file(
    tag_fields: Sequence[str],
    infile: Optional[os.PathLike] = None,
    outfile: Optional[os.PathLike] = None,
) -> int:
    log.debug("Create new JSON file using tag field(s) %r", tag_fields)
    if infile is not None:
        try:
            input_file = open(infile, encoding="utf-8", newline="")
        except OSError as err:
            log.error("Unable to open file for reading: %s", err)
            return 1
    else:
        input_file = nullcontext(sys.stdin)
    with input_file as csvfile:
        reader = csv.DictReader(csvfile)
        fieldnames = reader.fieldnames
        if (status := check_field_names(fieldnames, tag_fields)) is not None:
            return status
        table = OverlapTable(*tagsets_from_rows(reader, tag_fields))
        log.debug("Read from CSV file %r", csvfile)
    log.info(
        "Counted overlaps of %d 2-combinations of %d elements in %d sets (average %.2f elements per set)",
        math.comb(len(table), 2),
        len(table),
        table.n_sets,
        sum(table.counter.values()) / table.n_sets,
    )
    if outfile is not None:
        try:
            output_file = open(outfile, "x", encoding="utf-8")
        except FileExistsError:
            log.exception("Refusing to overwrite file: '%s'", outfile)
            return 1
        except OSError as err:
            log.error("Unable to open file for writing: %s", err)
            return 1
    else:
        output_file = nullcontext(sys.stdout)
    with output_file as jsonfile:
        table.to_json_stream(jsonfile)
        log.debug("Wrote to JSON file %r", jsonfile.name)
    return 0


def print_relatedtags(
    table: OverlapTable,
    tag_names: Sequence[str],
    limit: Optional[int] = None,
    file: Optional[IO] = None,
) -> None:
    """
    For each tag in *tag_names*, get related tag data from *table*,
    and print to *file* a table of related tag data.

    For each tag *A* (including *A* itself) the output table will contain four
    columns of info:

        1. The name of related tag *B*
        2. The total count of *B*
        3. The percent amount of the intersecting counts of *A* and *B*
           in proportion to the total count of *A*, i.e. n(*A* ∩ *B*) / n(*A*)
        4. The similarity metric between *A* and *B*

    The output will be sorted according to similarity (column 4) from highest
    to lowest, optionally limiting results to the *limit* most similar tags.
    """
    if file is None:
        file = sys.stdout
    # Disable text effects if output is not a terminal (e.g. a file or pipe)
    effect = "bold" if file.isatty() else ""
    field_formats = {
        "tag": FieldFormat(FieldFormat.REM, effect=effect),
        "count": FieldFormat(4),
        "overlap": FieldFormat(4),
        "similarity": FieldFormat(6),
    }
    tabulator = Tabulator(field_formats, total_width=80)
    rows: list[dict[str, str]] = []
    for tag in tag_names:
        # Start with a blank line
        rows.append(collections.defaultdict(str))
        rows.append(
            {"tag": "TAG", "count": "  N ", "overlap": " A∩B", "similarity": "SIMIL"}
        )
        cardinality = table.counter[tag]
        if not cardinality:
            # Bad tag
            rows.append(_format_row(tag))
            continue
        sims = most_common(table.similarities(tag), n=limit)
        for other_tag, similarity in sims:
            overlap = table.get(tag, other_tag) / cardinality
            row = _format_row(
                other_tag,
                count=table.counter[other_tag],
                overlap=overlap,
                similarity=similarity,
            )
            rows.append(row)
    for line in tabulator.tabulate(rows):
        print(line, file=file)


def _format_row(
    tag: str,
    count: int = 0,
    overlap: float = float("NaN"),
    similarity: float = float("NaN"),
) -> dict[str, str]:
    row = {"tag": tag}
    row["count"] = format(count, ">4d")
    row["overlap"] = format(overlap, ">4.0%")
    row["similarity"] = format(similarity, ">4.4f")
    return row


def clean_directory(pathname: StrPath) -> int:
    """
    Remove *.json files from directory *pathname* except the one with the
    greatest filename.
    """
    path = Path(pathname)
    if not path.is_dir():
        log.error(
            "Unable to clean directory: Does not exist or is not a directory: %s", path
        )
        return 1
    files = list(path.glob("*.json"))
    if not files:
        log.info("Nothing to clean: No files in directory: %s", path)
        return 0
    files.remove(max(files))
    for file in files:
        file.unlink()
    return 0


def get_new_json_filename(dir_path: Path) -> Path:
    datestring = time.strftime("%Y%m%d")
    incr = 0
    while True:
        full_name = dir_path / f"overlaps-{datestring}.{incr}.json"
        if not full_name.exists():
            return full_name
        incr += 1


def get_current_json_filename(dir_path: Path) -> Optional[Path]:
    if not dir_path.is_dir():
        return None
    return max(path for path in dir_path.glob("*.json"))
