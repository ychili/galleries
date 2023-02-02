# refresh.py
#
"""Use the management functionality to galleryms to refresh the table data."""

from __future__ import annotations

import csv
import json
import logging
import os
from collections.abc import Collection, Hashable, Iterator, MutableMapping
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, TypeVar, Union

from . import galleryms as gms

T = TypeVar("T")

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

    def merge_settings_from_files(
        self,
        fields: Collection[str],
        unified: Optional[Collection[os.PathLike]] = None,
        aliases: Optional[Collection[os.PathLike]] = None,
        implications: Optional[Collection[os.PathLike]] = None,
        removals: Optional[Collection[os.PathLike]] = None,
    ) -> None:
        """Set tag actions contained in files.

        Tag actions will be applied to default implicating fields *fields*,
        except for files in *unified* that contain field information.
        """
        fields = frozenset(fields)
        field_aliases: dict[frozenset[str], dict[str, str]] = {}
        field_impl: dict[frozenset[str], set[gms.BaseImplication]] = {}
        black_sets: dict[frozenset[str], gms.TagSet] = {}
        if aliases is not None:
            for filename in aliases:
                field_aliases[fields] = get_aliases(filename)
        if implications is not None:
            for filename in implications:
                field_impl[fields] = set(get_implications(filename))
        if removals is not None:
            black_sets[fields] = get_tags_from_file(*removals)
        if unified is not None:
            uof = UnifiedObjectFormat(default_fields=fields)
            for filename in unified:
                uof.update(get_unified(filename))
            for field, mapping in uof.get_aliases():
                field_aliases.setdefault(field, {}).update(mapping)
            for field, impl in uof.get_implications():
                field_impl.setdefault(field, set()).update(impl)
            for field, black in uof.get_removals():
                black_sets.setdefault(field, gms.TagSet()).update(black)
        for field_group, mapping in field_aliases.items():
            self.set_alias_tags(mapping, *field_group)
        for field_group, impl in field_impl.items():
            self.set_imply_tags(impl, *field_group)
        for field_group, black in black_sets.items():
            self.set_remove_tags(black, *field_group)


class UnifiedObjectFormat:
    """Extract tag actions from one, unified object format.

    Field information is given via top-level keys "fieldnames" = <array>
    and/or "fieldgroups" = <table>.
    """

    def __init__(
        self,
        obj: Optional[Mapping] = None,
        default_fields: Optional[Collection[str]] = None,
    ) -> None:
        self.field_tables: dict[frozenset[str], MutableMapping] = {}
        self.default_fields: frozenset[str] = frozenset(default_fields or [])
        if obj is not None:
            self.update(obj)

    def __bool__(self) -> bool:
        return bool(self.field_tables)

    def update(self, *others: Mapping) -> None:
        for obj in others:
            fieldnames = {
                str(name): frozenset([str(name)])
                for name in get_with_type(obj, "fieldnames", list)
            }
            fieldgroups = {
                str(name): frozenset(map(str, group))
                for name, group in get_with_type(obj, "fieldgroups", dict).items()
            }
            field_tables = {self.default_fields: obj}
            if fieldnames or fieldgroups:
                # Field names have been given -- overwrite top level
                field_tables = {
                    fields: get_with_type(obj, name, dict)
                    for name, fields in dict(**fieldnames, **fieldgroups).items()
                }
            for field, table in field_tables.items():
                # Within a field, tables are overwritten by update
                self.field_tables.setdefault(field, {}).update(table)

    def get_aliases(self) -> Iterator[tuple[frozenset[str], dict[str, str]]]:
        for field, table in self.field_tables.items():
            yield field, {
                str(alias): str(tag)
                for alias, tag in get_with_type(table, "aliases", dict).items()
            }

    def get_implications(
        self,
    ) -> Iterator[
        tuple[
            frozenset[str],
            set[Union[gms.DescriptorImplication, gms.RegularImplication]],
        ]
    ]:
        for field, table in self.field_tables.items():
            descriptors = {
                gms.DescriptorImplication(str(desc))
                for desc in get_with_type(table, "descriptors", list)
            }
            impl = {
                gms.RegularImplication(str(k), str(v))
                for k, v in get_with_type(table, "implications", dict).items()
            }
            yield field, descriptors | impl

    def get_removals(self) -> Iterator[tuple[frozenset[str], gms.TagSet]]:
        for field, table in self.field_tables.items():
            yield field, gms.TagSet(
                str(tag) for tag in get_with_type(table, "removals", list)
            )

    def set_tag_actions(self, gardener: Gardener) -> None:
        for field, aliases in self.get_aliases():
            gardener.set_alias_tags(aliases, *field)
        for field, implications in self.get_implications():
            gardener.set_imply_tags(implications, *field)
        for field, tag_set in self.get_removals():
            gardener.set_remove_tags(tag_set, *field)


def get_with_type(mapping: Mapping, name: Hashable, class_or_type: type[T]) -> T:
    """Get value from *mapping* using key *name* if it has the correct type.

    If the value is missing or is not an instance of *class_or_type*, return
    an empty instance of *class_or_type*.
    Additionally, emit a warning if the type is wrong.
    """
    try:
        value = mapping[name]
    except KeyError:
        return class_or_type()
    if isinstance(value, class_or_type):
        return value
    log.warning(
        "Key is present but value is wrong type (value is %s but should be %s): %s",
        type(value),
        class_or_type,
        name,
    )
    return class_or_type()


def get_unified(filename: os.PathLike, file_format: Optional[str] = None) -> Mapping:
    """Read *filename* and parse tag actions based on its file extension.

    ``*.toml`` files will be parsed as TOML. Anything else will be parsed as
    JSON.

    Or, force parsing as JSON if *file_format* == "json".
    """
    path = Path(filename)
    load = load_from_json
    if path.match("*.toml") and file_format != "json":
        load = load_from_toml
    try:
        obj = load(path)
    except OSError as err:
        log.error("Unable to open file for reading: %s", err)
        return {}
    return check_mapping(obj)


def check_mapping(obj: Any, default: type[Mapping] = dict) -> Mapping:
    """
    Return *obj* if it is a mapping. Otherwise return an empty instance of
    *default*.
    """
    if not isinstance(obj, Mapping):
        log.error("Decoded file was not mapping")
        return default()
    return obj


def load_from_toml(filename: os.PathLike) -> dict[str, Any]:
    """
    Do not attempt :module:`tomllib` import until this function is called.
    """
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib
    with open(filename, "rb") as file:
        try:
            return tomllib.load(file)
        except tomllib.TOMLDecodeError as err:
            log.error("Unable to decode file as TOML: %s", err)
            return {}


def load_from_json(filename: os.PathLike) -> Any:
    with open(filename, "rb") as file:
        try:
            return json.load(file)
        except json.JSONDecodeError as err:
            log.error("Unable to decode file as JSON: %s", err)
            return {}


def get_implications(filename: os.PathLike) -> frozenset[gms.BaseImplication]:
    """Read *filename* and parse implications based on its file extension."""
    extensions = ("dat", "txt", "asc", "list")
    path = Path(filename)
    if path.match("*.json"):
        data = check_mapping(load_from_json(path))
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
    data = check_mapping(load_from_json(filename))
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
