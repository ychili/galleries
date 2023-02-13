# refresh.py
#
"""Use the management functionality to galleryms to refresh the table data."""

from __future__ import annotations

import csv
import itertools
import json
import logging
import os
from collections import defaultdict
from collections.abc import Collection, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, Callable, Generic, Hashable, Iterable, Optional, TypeVar

from . import galleryms as gms

T = TypeVar("T")
Symbol = TypeVar("Symbol", bound=Hashable)

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

    def set_implicator(self, implicator: gms.Implicator, *fields: str) -> None:
        self._needed_fields.update(fields)
        for field in fields:
            self._set_tag_action(field, implicator.implicate)

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
        folder = gallery.get_folder(self._path_field, cwd=self._root_path)
        gallery.update_count(self._count_field, folder)


class UnifiedObjectFormat:
    """Extract tag actions from one, unified object format.

    Field information is given via top-level key "fieldnames" = <array>.
    """

    def __init__(self, mapping: Optional[Mapping] = None) -> None:
        self.field_tables: defaultdict[Optional[str], dict] = defaultdict(dict)
        if mapping is not None:
            self.update(mapping)

    def __bool__(self) -> bool:
        return bool(self.field_tables)

    def update(self, *others: Mapping) -> None:
        for obj in others:
            fieldnames = [str(name) for name in get_with_type(obj, "fieldnames", list)]
            for name in fieldnames:
                self.field_tables[name].update(get_with_type(obj, name, dict))
            if not fieldnames:
                # If no fieldnames, assign to default fieldname None
                self.field_tables[None].update(obj)

    def parse_aliases(self, key: Optional[str]) -> dict[str, str]:
        alias_table = get_with_type(self.field_tables[key], "aliases", dict).items()
        return {str(alias): str(tag) for alias, tag in alias_table}

    def get_aliases(self) -> Iterator[tuple[Optional[str], dict[str, str]]]:
        for field in self.field_tables.keys():
            yield field, self.parse_aliases(field)

    @staticmethod
    def _get_descriptors(table: Mapping) -> Iterator[gms.RegularImplication]:
        symbols = WordMultiplier()
        sets_table = get_with_type(table, "sets", dict)
        for name in sets_table:
            symbols.add_set(name, get_with_type(sets_table, name, list))
        unions_table = get_with_type(table, "unions", dict)
        for name in unions_table:
            elements = get_with_type(unions_table, name, list)
            symbols.add_union(name, *elements)
        chains_table = get_with_type(table, "chains", dict)
        for name in chains_table:
            chain = get_with_type(chains_table, name, list)
            if len(chain) < 2:
                log.warning("Chain has less than two names in it: %s", name)
                continue
            yield from symbols.implications_from_chain(chain)

    @staticmethod
    def _get_regulars(table: Mapping) -> set[gms.RegularImplication]:
        return {gms.RegularImplication(str(k), str(v)) for k, v in table.items()}

    def parse_implications(self, key: Optional[str]) -> set[gms.RegularImplication]:
        impl_table = get_with_type(self.field_tables[key], "implications", dict)
        impl = self._get_regulars(impl_table)
        desc_table = get_with_type(self.field_tables[key], "descriptors", dict)
        descriptors = frozenset(self._get_descriptors(desc_table))
        return impl | descriptors

    def get_implications(
        self,
    ) -> Iterator[tuple[Optional[str], set[gms.RegularImplication]]]:
        for field in self.field_tables.keys():
            yield field, self.parse_implications(field)

    def make_implicator(self, *field: Optional[str]) -> gms.Implicator:
        implications: set[gms.RegularImplication] = set()
        aliases: dict[str, str] = {}
        for name in field:
            implications.update(self.parse_implications(name))
            aliases.update(self.parse_aliases(name))
        return gms.Implicator(implications=implications, aliases=aliases)

    def implicators(self) -> Iterator[tuple[Optional[str], gms.Implicator]]:
        for implications, aliases in zip(self.get_implications(), self.get_aliases()):
            impl_field, impl = implications
            alias_field, alias = aliases
            assert impl_field == alias_field
            yield impl_field, gms.Implicator(implications=impl, aliases=alias)


class WordMultiplier(Generic[Symbol]):
    def __init__(self) -> None:
        self.symbols: defaultdict[Symbol, Iterable[str]] = defaultdict(frozenset)

    def add_set(self, name: Symbol, words: Iterable[str]) -> None:
        self.symbols[name] = frozenset(map(str, words))

    def add_union(self, union_name: Symbol, *sets: Symbol) -> None:
        union_set = (self.symbols[name] for name in sets)
        self.symbols[union_name] = Chain(*union_set)

    def chain(
        self, names: Sequence[Symbol], join: Callable[[Iterable[str]], T] = tuple
    ) -> Iterator[tuple[T, T]]:
        descriptors = [self.symbols[name] for name in reversed(names)]
        for consequent, antecedent in set_chains(*descriptors):
            yield join(reversed(antecedent)), join(reversed(consequent))

    def implications_from_chain(
        self, names: Sequence[Symbol]
    ) -> Iterator[gms.RegularImplication]:
        for antecedent, consequent in self.chain(names, join="_".join):
            yield gms.RegularImplication(antecedent=antecedent, consequent=consequent)


class Chain(Iterable[T]):
    def __init__(self, *iterables: Iterable[T]) -> None:
        self.iterables = iterables

    def __iter__(self) -> Iterator[T]:
        yield from itertools.chain(*self.iterables)


def set_chains(
    *word_sets: Iterable[str],
) -> Iterator[tuple[tuple[str, ...], tuple[str, ...]]]:
    for group in itertools.product(*word_sets):
        group = iter(group)
        result_stack = [next(group)]
        for elem in group:
            consequent = tuple(result_stack)
            result_stack.append(elem)
            yield consequent, tuple(result_stack)


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
    obj = load(path)
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
    Do not attempt :mod:`tomllib` import until this function is called.
    """
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib
    with open(filename, "rb") as file:
        try:
            return tomllib.load(file)
        except tomllib.TOMLDecodeError as err:
            log.error("Unable to decode file as TOML: In %s: %s", filename, err)
            return {}


def load_from_json(filename: os.PathLike) -> Any:
    with open(filename, "rb") as file:
        try:
            return json.load(file)
        except json.JSONDecodeError as err:
            log.error("Unable to decode file as JSON: In %s: %s", filename, err)
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
