# refresh.py
#
"""Use the management functionality to galleryms to refresh the table data."""

from __future__ import annotations

import contextlib
import csv
import dataclasses
import itertools
import json
import logging
import os
import re
from collections import defaultdict
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence, Set
from pathlib import Path
from typing import Any, Callable, Generic, Hashable, Optional, TypeVar

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


@dataclasses.dataclass
class _TagActionsContainer:
    fields: frozenset[str]
    implications: set[gms.RegularImplication] = dataclasses.field(default_factory=set)
    aliases: dict[str, str] = dataclasses.field(default_factory=dict)


class TagActionsObject:
    """Extract tag actions from one, unified object format."""

    extr: ObjectExtractor

    def __init__(self, default_tag_fields: Optional[Iterable[str]] = None) -> None:
        self.default_tag_fields = frozenset(default_tag_fields or [])
        # A pool is the set of tag actions that apply to a given set of fields
        self._pools: dict[frozenset[str], _TagActionsContainer] = {}
        # A field's spec is the set of pools that apply to a given field
        self._field_spec: defaultdict[str, set[frozenset[str]]] = defaultdict(set)

    def read_file(
        self, filename: os.PathLike, file_format: Optional[str] = None
    ) -> None:
        """Read *filename* and parse tag actions based on its file extension.

        ``*.toml`` files will be parsed as TOML. Anything else will be parsed
        as JSON.

        Or, force parsing as JSON if *file_format* == "json".
        """
        path = Path(filename)
        load = load_from_json
        if path.match("*.toml") and file_format != "json":
            load = load_from_toml
        obj = load(path)
        self.update(obj, source=path)

    def update(self, obj: Any, source: Optional[os.PathLike] = None) -> None:
        self.extr = ObjectExtractor(source=source)
        obj = self.extr.dict(obj)
        if not obj:
            return
        dests = self._parse_fields(obj)
        for dest, table_name in dests.items():
            if table_name is None:
                table = contextlib.nullcontext(obj)
            else:
                table = self.extr.get(obj, table_name)
            with table:
                if not table:
                    self.extr.warn("Table not found with name: %s", table_name)
                    continue
                for field in dest:
                    self._field_spec[field].add(dest)
                tac = self._pools.setdefault(dest, _TagActionsContainer(fields=dest))
                tac.aliases.update(self._parse_aliases(table))
                tac.implications.update(self._parse_implications(table))

    def _parse_fields(self, obj: Mapping) -> dict[frozenset[str], Optional[str]]:
        dests: dict[frozenset[str], Optional[str]] = {}
        for fieldname in self.extr.get_list(obj, "fieldnames"):
            field = str(fieldname)
            dests[frozenset([field])] = field
        for groupname, fieldnames in self.extr.get_items(obj, "fieldgroups"):
            table_name = str(groupname)
            dest = [str(field) for field in self.extr.list(fieldnames)]
            if not dest:
                self.extr.warn("Can't use an empty fieldgroup")
                continue
            dests[frozenset(dest)] = table_name
        if not dests:
            dests[self.default_tag_fields] = None
        return dests

    def _parse_aliases(self, obj: Any) -> Iterator[tuple[str, str]]:
        for key, value in self.extr.get_items(obj, "aliases"):
            yield str(key), str(value)

    def _parse_implications(self, obj: Any) -> Iterator[gms.RegularImplication]:
        yield from self._parse_regulars(obj)
        with self.extr.get_dict(obj, "descriptors") as table:
            yield from self._parse_descriptors(table)

    def _parse_regulars(self, obj: Any) -> Iterator[gms.RegularImplication]:
        for key, value in self.extr.get_items(obj, "implications"):
            yield gms.RegularImplication(antecedent=str(key), consequent=str(value))

    def _parse_descriptors(self, table: Any) -> Iterator[gms.RegularImplication]:
        symbols: WordMultiplier = WordMultiplier()
        for name, words in self.extr.get_items(table, "sets"):
            symbols.add_set(name, self.extr.list(words))
        for name, elements in self.extr.get_items(table, "unions"):
            if name in symbols:
                self.extr.warn("Over-writing set name with union: %s", name)
            elements = self.extr.list(elements)
            try:
                symbols.add_union(name, *elements)
            except KeyError as err:
                self.extr.warn("Bad set/union name: %s", err)
        for name, elements in self.extr.get_items(table, "chains"):
            chain = self.extr.list(elements)
            if len(chain) < 2:
                self.extr.warn("Chain has fewer than two names in it: %s", name)
                continue
            try:
                yield from symbols.implications_from_chain(chain)
            except KeyError as err:
                self.extr.warn("Bad set/union name: %s", err)

    def _make_implicator(self, spec: Set[frozenset[str]]) -> gms.Implicator:
        spec = frozenset(spec)
        implic = gms.Implicator()
        for pool in spec:
            data = self._pools[pool]
            implic.aliases.update(data.aliases)
            for impl in data.implications:
                implic.add(impl)
        return implic

    def get_implicator(self, fieldname: str) -> gms.Implicator:
        spec = self._field_spec[fieldname]
        return self._make_implicator(spec)

    def _spec_fields(self) -> defaultdict[frozenset[frozenset[str]], set[str]]:
        spec_fields: defaultdict[frozenset[frozenset[str]], set[str]] = defaultdict(set)
        for field, spec in self._field_spec.items():
            spec_fields[frozenset(spec)].add(field)
        return spec_fields

    def implicators(self) -> Iterator[tuple[set[str], gms.Implicator]]:
        for spec, fields in self._spec_fields().items():
            yield fields, self._make_implicator(spec)


class ObjectExtractor:
    def __init__(
        self,
        source: Optional[os.PathLike] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.source = source or "<???>"
        self.logger = logger or logging.getLogger(__name__)
        self._parse_stack: list[Optional[str]] = []

    def items(self, mapping: Mapping) -> Iterator[tuple[Any, Any]]:
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
    def get(self, mapping: Mapping, key: Hashable, default: Any = None) -> Iterator:
        self._parse_stack.append(str(key))
        try:
            value = mapping.get(key, default=default)
        except AttributeError:
            self.warn("Expected a mapping got a %s", type(mapping))
            yield default
        else:
            yield value
        self._parse_stack.pop()

    def object(self, value: Any, class_or_type: type[T]) -> T:
        if isinstance(value, class_or_type):
            return value
        self.warn(
            "Key is present but value is wrong type (value is %s but should be %s)",
            type(value),
            class_or_type,
        )
        return class_or_type()

    def list(self, value: Any) -> list:
        return self.object(value, list)

    def dict(self, value: Any) -> dict:
        return self.object(value, dict)

    def get_list(self, mapping: Mapping, key: Hashable) -> list:
        with self.get(mapping, key, default=[]) as value:
            if not value:
                return []
            return self.list(value)

    @contextlib.contextmanager
    def get_dict(self, mapping: Mapping, key: Hashable) -> Iterator:
        with self.get(mapping, key, default={}) as value:
            yield self.dict(value)

    def get_items(self, mapping: Mapping, key: Hashable) -> Iterator[tuple[Any, Any]]:
        with self.get(mapping, key, default={}) as value:
            yield from self.items(value)

    def warn(self, msg: str, *args: Any) -> None:
        self.logger.warning(
            "In %s: At %s: %s", self.source, toml_address(self._parse_stack), msg % args
        )


class WordMultiplier(Generic[Symbol]):
    """Generate implications by compounding sets of words

    By default compound words by joining them with a single underscore ("_"),
    or by calling *join* if provided.

    >>> wm = WordMultiplier()
    >>> wm.add_set("letters", "AB")
    >>> wm.add_set("numbers", "12")
    >>> sorted(wm.chain(["letters", "numbers"], join="".join))
    [('A1', '1'), ('A2', '2'), ('B1', '1'), ('B2', '2')]
    """

    def __init__(self, join: Callable[[Iterable[str]], str] = "_".join) -> None:
        self.join = join
        self.symbols: dict[Symbol, frozenset[str]] = {}

    def __contains__(self, value: Symbol) -> bool:
        return value in self.symbols

    def add_set(self, name: Symbol, words: Iterable[str]) -> None:
        """Map set of words *words* to *name*."""
        self.symbols[name] = frozenset(map(str, words))

    def add_union(self, union_name: Symbol, *sets: Symbol) -> None:
        """Map the union of sets with names *sets* to *union_name*."""
        union_set = (self.symbols[name] for name in sets)
        self.symbols[union_name] = frozenset(itertools.chain(*union_set))

    def chain(
        self, names: Sequence[Symbol], join: Callable[[Iterable[str]], T] = tuple
    ) -> Iterator[tuple[T, T]]:
        descriptors = [self.symbols[name] for name in reversed(names)]
        for consequent, antecedent in set_chains(*descriptors):
            yield join(reversed(antecedent)), join(reversed(consequent))

    def implications_from_chain(
        self, names: Sequence[Symbol]
    ) -> Iterator[gms.RegularImplication]:
        """Yield implications from sets referred to by *names*.

        For a chain of two sets A and B, yield ab -> b for each word in each
        set. With a third set C, yield abc -> bc and bc -> c. And so on.
        """
        for antecedent, consequent in self.chain(names, join=self.join):
            yield gms.RegularImplication(antecedent=antecedent, consequent=consequent)


def set_chains(
    *word_sets: Iterable[str],
) -> Iterator[tuple[tuple[str, ...], tuple[str, ...]]]:
    """
    For each n-tuple in the product of n iterables *word_sets*, yield pairs
    ((a,),(a,b)), ((a,b),(a,b,c)), ((a,b,c),(a,b,c,d)), and so on, up to n.
    """
    for group in itertools.product(*word_sets):
        result_stack = [group[0]]
        for elem in group[1:]:
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


def toml_address(keys: Iterable[Optional[str]]) -> str:
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
