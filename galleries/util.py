# util.py

from __future__ import annotations

import contextlib
import csv
import logging
import os
import re
import sys
from collections.abc import Collection, Iterable, Iterator
from typing import Optional, Union

from .galleryms import Gallery, Reader

log = logging.getLogger(__name__)


class FieldNotFoundError(Exception):
    pass


@contextlib.contextmanager
def read_db(
    file: Optional[os.PathLike] = None, fieldnames: Optional[Iterable[str]] = None
) -> Iterator[Reader]:
    if file is None or file == sys.stdin:
        file_cm = contextlib.nullcontext(sys.stdin)
    else:
        file_cm = open(file, encoding="utf-8", newline="")
    with file_cm as infile:
        reader = csv.DictReader(infile)
        if reader.fieldnames:
            for field in fieldnames or ():
                if field not in reader.fieldnames:
                    raise FieldNotFoundError(field)
            yield Reader(reader)
        else:
            yield Reader()


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
