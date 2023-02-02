# refresh.py
#
"""Use the management functionality to galleryms to refresh the table data."""

from __future__ import annotations

import csv
import json
import logging
import os
from collections.abc import Collection, Iterator, Mapping
from pathlib import Path
from typing import Callable, Optional

from . import galleryms as gms

log = logging.getLogger(__name__)


class Gardener:
    """Garden galleries."""

    def __init__(self) -> None:
        self._needed_fields: set[str] = set()
        self._tag_fields: dict[str, list[Callable[[gms.TagSet], None]]] = {}
        self._do_count: Callable[[gms.Gallery], None] = lambda *args, **kwds: None
        self._path_field: str = str()
        self._count_field: str = str()
        self._root_path: Path = Path()

    def set_update_count(
        self, path_field: str, count_field: str, root_path: Optional[gms.StrPath] = None
    ) -> None:
        self._needed_fields.update([path_field, count_field])
        self._do_count = self._update_count
        self._path_field = path_field
        self._count_field = count_field
        self._root_path = Path(root_path or Path.cwd())

    def _set_tag_action(
        self, field: str, func: Optional[Callable[[gms.TagSet], None]] = None
    ) -> None:
        actions = self._tag_fields.setdefault(field, [])
        if func is None:
            return
        actions.append(func)

    def set_normalize_tags(self, *fields: str) -> None:
        self._needed_fields.update(fields)
        for field in fields:
            self._set_tag_action(field)

    def set_imply_tags(
        self, implications: Collection[gms.BaseImplication], *fields: str
    ) -> None:
        self._needed_fields.update(fields)
        for field in fields:
            self._set_tag_action(
                field, lambda ts: gms.TagSet.apply_implications(ts, implications)
            )

    def set_remove_tags(self, mask: gms.TagSet, *fields: str) -> None:
        self._needed_fields.update(fields)
        for field in fields:
            self._set_tag_action(
                field, lambda ts: gms.TagSet.difference_update(ts, mask)
            )

    def set_alias_tags(self, aliases: Mapping[str, str], *fields: str) -> None:
        self._needed_fields.update(fields)
        for field in fields:
            self._set_tag_action(
                field, lambda ts: gms.TagSet.apply_aliases(ts, aliases)
            )

    def garden_rows(
        self, reader: csv.DictReader, fieldnames: Optional[Collection[str]] = None
    ) -> Iterator[gms.Gallery]:
        """
        After operation parameters have been set, yield gardened galleries.
        """
        if fieldnames is not None:
            for field in self._needed_fields:
                if field not in fieldnames:
                    raise KeyError(field)
        for row in reader:
            gallery = gms.Gallery(row)
            self._do_count(gallery)
            for field, actions in self._tag_fields.items():
                tags = gallery.normalize_tags(field)
                for action in actions:
                    action(tags)
                gallery[field] = tags
            yield gallery

    def _update_count(self, gallery: gms.Gallery) -> None:
        log.info("Checking folder: %s", gallery[self._path_field])
        folder = gallery.check_folder(self._path_field, cwd=self._root_path)
        gallery.update_count(self._count_field, folder)


def get_implications(filename: os.PathLike) -> frozenset[gms.BaseImplication]:
    """Read *filename* and parse implications based on its file extension."""
    extensions = ("dat", "txt", "asc", "list")
    path = Path(filename)
    if path.match("*.json"):
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        return frozenset(
            gms.RegularImplication(str(k), str(v)) for k, v in data.items()
        )
    if any(path.match(f"*.{ext}") for ext in extensions):
        text = path.read_text(encoding="utf-8")
        return frozenset(gms.DescriptorImplication(desc) for desc in text.split())
    log.warning(
        "Implications file exists but does not match known file extensions: %s",
        filename,
    )
    return frozenset()


def get_aliases(filename: os.PathLike) -> dict[str, str]:
    path = Path(filename)
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    return {str(alias): str(tag) for alias, tag in data.items()}


def get_tags_from_file(*filepaths: os.PathLike) -> gms.TagSet:
    """
    Merge (union) whitespaced-separated tags from files in *filepaths* into one
    ``TagSet``.
    """
    tags = gms.TagSet()
    for path in filepaths:
        text = Path(path).read_text(encoding="utf-8")
        tags.update(gms.TagSet.from_tagstring(text))
    return tags


def traverse_fs(root: Path, leaves_only: bool = False) -> Iterator[tuple[Path, int]]:
    """Yield descendant directories of *root* and their file counts.

    Directories with a file count of zero are not yielded.
    Symlinks are not followed.
    If *leaves_only* is True (default is False), only yield directories that
    have no child directories of their own.
    """
    total_count: int = 0
    child_nodes: list[Path] = []
    try:
        for path in root.iterdir():
            if not path.name.startswith("."):
                total_count += 1
                if path.is_dir() and not path.is_symlink():
                    child_nodes.append(path)
    except OSError as err:
        log.info("Cannot get contents of directory: %s", err)
        return
    if not leaves_only or not child_nodes:
        file_count = total_count - len(child_nodes)
        if file_count > 0:
            yield root, file_count
    for child in child_nodes:
        yield from traverse_fs(child, leaves_only=leaves_only)
