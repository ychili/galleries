# util.py

"""Utility functions, used and shared by all modules"""

from __future__ import annotations

import contextlib
import csv
import os
import re
import sys
from collections.abc import Callable, Collection, Iterator, Sequence
from typing import Iterable, Optional, Union

import rich.console

from .galleryms import Gallery

# I/O UTILITIES
# -------------

console = rich.console.Console()


class FieldNotFoundError(Exception):
    pass


class FieldMismatchError(Exception):
    def __init__(
        self, row: list[str], fieldnames: Sequence[str], line_num: int
    ) -> None:
        self.row = row
        self.fieldnames = fieldnames
        self.line_num = line_num
        self.args = (row, fieldnames, line_num)


class ExtraFieldError(FieldMismatchError):
    def __str__(self) -> str:
        n_extra = len(self.row) - len(self.fieldnames)
        return f"line {self.line_num}: {n_extra} extra field(s) in row: {self.row}"


class MissingFieldError(FieldMismatchError):
    def __str__(self) -> str:
        n_missing = len(self.fieldnames) - len(self.row)
        return f"line {self.line_num}: {n_missing} missing field(s) in row: {self.row}"


class Reader(Iterable[Gallery]):
    def __init__(self, reader: StrictReader) -> None:
        self._reader = reader
        self.fieldnames = reader.fieldnames or []

    def __iter__(self) -> Iterator[Gallery]:
        yield from self._reader


class StrictReader(csv.DictReader):
    """A DictReader that doesn't allow short or long rows"""

    def __next__(self) -> Gallery:
        if self.line_num == 0:
            # Used only for its side effect.
            self.fieldnames  # pylint: disable=pointless-statement
            # If self.fieldnames is None then StopIteration will be raised on
            # the next line.
        row = next(self.reader)
        self.line_num = self.reader.line_num

        while row == []:
            row = next(self.reader)
        self.fieldnames: Sequence[str]  # Assert type
        l_fn = len(self.fieldnames)
        l_row = len(row)
        if l_fn < l_row:
            # Extra fields
            raise ExtraFieldError(row, self.fieldnames, self.line_num)
        if l_fn > l_row:
            # Missing fields
            raise MissingFieldError(row, self.fieldnames, self.line_num)
        return Gallery(zip(self.fieldnames, row))


@contextlib.contextmanager
def read_db(
    file: Optional[os.PathLike] = None, fieldnames: Optional[Iterable[str]] = None
) -> Iterator[Reader]:
    """Open *file*, and read DB inside a context manager.

    If *fieldnames* is given, ``FieldNotFoundError`` is raised if any field
    names are missing from the DB.
    """
    if file is None or file == sys.stdin:
        file_cm = contextlib.nullcontext(sys.stdin)
    else:
        file_cm = open(file, encoding="utf-8", newline="")
    with file_cm as infile:
        reader = Reader(StrictReader(infile))
        if reader.fieldnames:
            for field in fieldnames or ():
                if field not in reader.fieldnames:
                    raise FieldNotFoundError(field)
        yield reader


def write_galleries(
    rows: Iterable[Gallery],
    fieldnames: Collection[str],
    file: Optional[os.PathLike] = None,
) -> None:
    """Write *rows* with field names *fieldnames* in unformatted CSV.

    Writes to standard output or to *file*, if given.
    """
    if file is None or file == sys.stdout:
        file_cm = contextlib.nullcontext(sys.stdout)
    else:
        file_cm = open(file, "w", encoding="utf-8", newline="")
    with file_cm as outfile:
        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# SORTING FUNCTIONS
# -----------------


def sort_by_field(
    galleries: Iterable[Gallery], sort_field: str, *, reverse: bool = False
) -> list[Gallery]:
    sort_key = alphanum_getter(sort_field)
    if isinstance(galleries, list):
        galleries.sort(key=sort_key, reverse=reverse)
        return galleries
    return sorted(galleries, key=sort_key, reverse=reverse)


def alphanum_getter(field: str) -> Callable[[Gallery], list[Union[int, str]]]:
    """Return a key function that sorts galleries on *field*."""

    def getter(gallery: Gallery) -> list[Union[int, str]]:
        # As it stands, values should already be str, but convert anyway
        # to be safe.
        value = str(gallery[field]).casefold()
        return alphanum_key(value)

    return getter


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
