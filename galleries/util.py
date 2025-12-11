# util.py

"""Utility functions, used and shared by all modules"""

from __future__ import annotations

import contextlib
import csv
import json
import logging
import os
import re
import sys
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, Sequence
from typing import TYPE_CHECKING, Any, TypeVar

import rich.console

from . import PROG
from .galleryms import Gallery

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

if TYPE_CHECKING:
    from _typeshed import StrOrBytesPath, SupportsWrite

log = logging.getLogger(PROG)


class Const:
    """Namespace for constants used in pattern matching."""

    sentinel = object()


# PARSING HELPERS
# ---------------


T = TypeVar("T")
KT = TypeVar("KT")
VT = TypeVar("VT")


class ObjectExtractor:
    """Helper for validating types within mappings/objects

    Help keep track of position in the object tree, so that warnings emitted
    will include this info.
    """

    def __init__(
        self,
        source: str | None = None,
        logger: logging.Logger | logging.LoggerAdapter | None = None,
    ) -> None:
        self.source = source or "<???>"
        self.logger = logger or logging.getLogger(PROG)
        self._parse_stack: list[str | None] = []

    def items(self, mapping: Mapping[T, VT]) -> Iterator[tuple[T, VT]]:
        try:
            mapping_items = mapping.items()
        except AttributeError:
            self.warn("Expected a mapping, got a %s", type(mapping))
            yield from {}
        else:
            for key, value in mapping_items:
                self._parse_stack.append(str(key))
                yield key, value
                self._parse_stack.pop()

    @contextlib.contextmanager
    def get(self, mapping: Mapping[KT, VT], key: KT, default: VT) -> Iterator[VT]:
        self._parse_stack.append(str(key))
        try:
            value = mapping.get(key, default)
        except AttributeError:
            self.warn("Expected a mapping got a %s", type(mapping))
            yield default
        else:
            yield value
        finally:
            self._parse_stack.pop()

    def object(self, value: object, class_or_type: type[T]) -> T:
        if isinstance(value, class_or_type):
            return value
        self.warn(
            "Key is present but value is wrong type (value is %s but should be %s)",
            type(value),
            class_or_type,
        )
        return class_or_type()

    def list(self, value: object) -> list:
        return self.object(value, list)

    def dict(self, value: object) -> dict:
        return self.object(value, dict)

    def get_list(self, mapping: Mapping[KT, list], key: KT) -> list:
        with self.get(mapping, key, default=[]) as value:
            return self.list(value)

    @contextlib.contextmanager
    def get_dict(self, mapping: Mapping[KT, dict], key: KT) -> Iterator[dict]:
        with self.get(mapping, key, default={}) as value:
            yield self.dict(value)

    def get_items(
        self, mapping: Mapping[KT, Mapping[T, VT]], key: KT
    ) -> Iterator[tuple[T, VT]]:
        with self.get(mapping, key, default={}) as value:
            yield from self.items(value)

    def warn(self, msg: str, *args: object) -> None:
        self.logger.warning(
            "In %s: At %s: %s", self.source, toml_address(self._parse_stack), msg % args
        )


def toml_address(keys: Iterable[str | None]) -> str:
    """Quote *keys* according to TOML rules and join by periods.

    Empty strings and Nones are skipped.

    >>> toml_address([None, "bare", "two words", "bang!"])
    'bare."two words"."bang!"'
    """
    bare_chars = "[A-Za-z0-9_-]+"
    quoted = []
    for key in keys:
        if not key:
            continue
        if re.fullmatch(bare_chars, key):
            quoted.append(key)
        else:
            quoted.append(f'"{key}"')
    return ".".join(quoted)


# I/O UTILITIES
# -------------

console = rich.console.Console(markup=False)


class FieldNotFoundError(Exception):
    pass


class FieldMismatchError(Exception):
    def __init__(
        self, row: list[str], fieldnames: Sequence[str], line_num: int
    ) -> None:
        self.row = row
        self.fieldnames = fieldnames
        self.line_num = line_num
        super().__init__(row, fieldnames, line_num)


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
        assert (
            self.fieldnames is not None
        ), "DictReader.__next__ did not behave as expected"
        self.line_num = self.reader.line_num

        while row == []:
            row = next(self.reader)
        l_fn = len(self.fieldnames)
        l_row = len(row)
        if l_fn < l_row:
            # Extra fields
            raise ExtraFieldError(row, self.fieldnames, self.line_num)
        if l_fn > l_row:
            # Missing fields
            raise MissingFieldError(row, self.fieldnames, self.line_num)
        return Gallery(zip(self.fieldnames, row, strict=True))


@contextlib.contextmanager
def read_db(
    file: StrOrBytesPath | Iterable[str] | None = None,
    fieldnames: Iterable[str] | None = None,
) -> Iterator[Reader]:
    """Open *file*, and read DB inside a context manager.

    If *file* is str, bytes, or path-like, it is treated as a path and opened
    for reading. If *file* is not given or None, read from standard input.
    If *fieldnames* is given, ``FieldNotFoundError`` is raised if any field
    names are missing from the DB.
    """
    match file:
        case str() | bytes() | os.PathLike():
            file_cm = open(file, encoding="utf-8", newline="")
        case None:
            file_cm = contextlib.nullcontext(sys.stdin)
        case _:
            file_cm = contextlib.nullcontext(file)
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
    file: StrOrBytesPath | SupportsWrite[str] | None = None,
    opener: Callable[[str, int], int] | None = None,
) -> None:
    """Write *rows* with field names *fieldnames* in unformatted CSV.

    If *file* is str, bytes, or path-like, it is treated as a path and opened
    for writing. If *file* is not given or None, write to standard output.
    The argument *opener* will be passed to ``open``'s *opener* parameter.
    """
    match file:
        case str() | bytes() | os.PathLike():
            file_cm = open(file, "w", encoding="utf-8", newline="", opener=opener)
        case None:
            file_cm = contextlib.nullcontext(sys.stdout)
        case _:
            file_cm = contextlib.nullcontext(file)
    with file_cm as outfile:
        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def load_from_toml(filename: StrOrBytesPath) -> dict[str, Any]:
    with open(filename, "rb") as file:
        try:
            return tomllib.load(file)
        except tomllib.TOMLDecodeError as err:
            log.error("Unable to decode file as TOML: In %s: %s", filename, err)
            return {}


def load_from_json(filename: StrOrBytesPath) -> Any:
    with open(filename, "rb") as file:
        try:
            return json.load(file)
        except json.JSONDecodeError as err:
            log.error("Unable to decode file as JSON: In %s: %s", filename, err)
            return {}


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


def alphanum_getter(field: str) -> Callable[[Gallery], list[int | str]]:
    """Return a key function that sorts galleries on *field*."""

    def getter(gallery: Gallery) -> list[int | str]:
        # As it stands, values should already be str, but convert anyway
        # to be safe.
        value = str(gallery[field]).casefold()
        return alphanum_key(value)

    return getter


def atoi(s: str) -> int | str:
    try:
        return int(s)
    except ValueError:
        return s


def alphanum_key(s: str) -> list[int | str]:
    """Turn a string into a list of string and number chunks.

    >>> alphanum_key("z23a")
    ['z', 23, 'a']
    """
    return [atoi(c) for c in re.split("([0-9]+)", s)]
