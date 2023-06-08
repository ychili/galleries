# util.py

from __future__ import annotations

import contextlib
import csv
import logging
import os
import re
import sys
from collections.abc import Collection, Iterable, Iterator, Sequence
from typing import Optional, TextIO, Union

from .galleryms import Gallery, TagSet

log = logging.getLogger(__name__)


class FieldNotFoundError(Exception):
    pass


def read_galleries(
    fieldnames: Iterable[str], file: Optional[os.PathLike] = None
) -> Iterator[Gallery]:
    # TODO: add info/debug logs
    if file is None or file == sys.stdin:
        file_cm = contextlib.nullcontext(sys.stdin)
    else:
        file_cm = open(file, encoding="utf-8", newline="")
    with file_cm as infile:
        reader = csv.DictReader(infile)
        if not reader.fieldnames:
            return
        for field in fieldnames:
            if field not in reader.fieldnames:
                raise FieldNotFoundError(field)
        for row in reader:
            yield Gallery(row)


def write_galleries(
    rows: Iterable[Gallery],
    fieldnames: Collection[str],
    file: Optional[os.PathLike] = None,
) -> None:
    # TODO: add info/debug logs
    if file is None or file == sys.stdout:
        file_cm = contextlib.nullcontext(sys.stdout)
    else:
        file_cm = open(file, "w", encoding="utf-8", newline="")
    with file_cm as outfile:
        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def tagsets_from_rows(
    rows: Iterable[dict[str, str]], tag_fields: Sequence[str]
) -> Iterator[TagSet]:
    for row in rows:
        yield Gallery(row).merge_tags(*tag_fields)


def write_rows(
    rows: Iterable[Gallery], fieldnames: Sequence[str], file: TextIO = sys.stdout
) -> None:
    """Write *rows* to *file* in unformatted CSV."""
    dict_writer = csv.DictWriter(file, fieldnames=fieldnames)
    dict_writer.writeheader()
    dict_writer.writerows(rows)


def check_field_names(
    fieldnames: Optional[Collection[str]], tag_fields: Sequence[str]
) -> Optional[int]:
    """Check that all *tag_fields* are in *fieldnames*.

    Returns:
        0 if *fieldnames* is empty or None
        1 if a tag field could not be found in *fieldnames*
        None if okay
    """
    log.debug("fieldnames from file: %r", fieldnames)
    if not fieldnames:
        return 0
    for field in tag_fields:
        if field not in fieldnames:
            log.error("Field not in file: %s", field)
            return 1
    return None


def atoi(s: str) -> Union[int, str]:
    try:
        return int(s)
    except ValueError:
        return s


def alphanum_key(s: str) -> list[Union[int, str]]:
    """Turn a string into a list of string and number chunks.

    >>> alphanum_key("z23a")
    ['z', 23, 'a']
    """
    return [atoi(c) for c in re.split("([0-9]+)", s)]
