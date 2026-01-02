# refresh.py
#
"""Use the management functionality of galleryms to refresh the table data."""

from __future__ import annotations

import contextlib
import dataclasses
import itertools
import logging
import unicodedata
from collections import ChainMap, defaultdict
from collections.abc import (
    Callable,
    Collection,
    Hashable,
    Iterable,
    Iterator,
    Mapping,
    Sequence,
)
from collections.abc import Set as AbstractSet
from pathlib import Path
from typing import TYPE_CHECKING, Generic, TypeVar

from . import PROG
from . import galleryms as gms
from . import util

if TYPE_CHECKING:
    from _typeshed import StrOrBytesPath, StrPath

T = TypeVar("T")
KT = TypeVar("KT")
VT = TypeVar("VT")
Symbol = TypeVar("Symbol", bound=Hashable)

log = logging.getLogger(PROG)


class FolderPathError(OSError):
    """Error with a path value"""


class DuplicateValueError(Exception):
    def __init__(self, field: str, value: str) -> None:
        super().__init__(field, value)
        self.field = field
        self.value = value


class Gardener:
    """Garden galleries."""

    def __init__(self) -> None:
        self.needed_fields: set[str] = set()
        self._tag_fields: dict[str, list[Callable[[gms.TagSet], None]]] = {}
        self._do_count: Callable[[gms.Gallery], None] = lambda *args, **kwds: None
        self._path_field: str = ""
        self._count_field: str = ""
        self._root_path: Path = Path()
        self._unique_fields: dict[str, set[object]] = {}

    def set_update_count(
        self, path_field: str, count_field: str, root_path: StrPath | None = None
    ) -> None:
        self.needed_fields.update([path_field, count_field])
        self._do_count = self._update_count
        self._path_field = path_field
        self._count_field = count_field
        self._root_path = Path(root_path or Path.cwd())

    def _set_tag_action(
        self, field: str, func: Callable[[gms.TagSet], None] | None = None
    ) -> None:
        actions = self._tag_fields.setdefault(field, [])
        if func is None:
            return
        actions.append(func)

    def set_normalize_tags(self, *fields: str) -> None:
        self.needed_fields.update(fields)
        for field in fields:
            self._set_tag_action(field)

    def set_imply_tags(
        self, implications: Collection[gms.BaseImplication], *fields: str
    ) -> None:
        self.needed_fields.update(fields)
        for field in fields:
            self._set_tag_action(
                field, lambda ts: type(ts).apply_implications(ts, implications)
            )

    def set_remove_tags(self, mask: gms.TagSet, *fields: str) -> None:
        self.needed_fields.update(fields)
        for field in fields:
            self._set_tag_action(field, lambda ts: type(ts).difference_update(ts, mask))

    def set_alias_tags(self, aliases: Mapping[str, str], *fields: str) -> None:
        self.needed_fields.update(fields)
        for field in fields:
            self._set_tag_action(field, lambda ts: type(ts).apply_aliases(ts, aliases))

    def set_implicator(self, implicator: gms.Implicator, *fields: str) -> None:
        self.needed_fields.update(fields)
        for field in fields:
            self._set_tag_action(field, implicator.implicate)

    def set_unique(self, *fields: str) -> None:
        self.needed_fields.update(fields)
        for field in fields:
            self._unique_fields[field] = set()

    def garden_rows(
        self, reader: Iterable[gms.Gallery], fieldnames: Collection[str] | None = None
    ) -> Iterator[gms.Gallery]:
        """
        After operation parameters have been set, yield gardened galleries.
        """
        if fieldnames is not None:
            for field in self.needed_fields:
                if field not in fieldnames:
                    raise util.FieldNotFoundError(field)
        for gallery in reader:
            self._check_uniqueness(gallery)
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
        try:
            gallery.update_count(self._count_field, folder)
        except (FileNotFoundError, NotADirectoryError) as err:
            raise FolderPathError(err) from err

    def _check_uniqueness(self, gallery: gms.Gallery) -> None:
        for field, values_seen in self._unique_fields.items():
            value = unicodedata.normalize("NFC", str(gallery[field]))
            if value in values_seen:
                raise DuplicateValueError(field, value)
            values_seen.add(value)


@dataclasses.dataclass
class _TagActionsContainer:
    fields: frozenset[str]
    implications: set[gms.RegularImplication] = dataclasses.field(default_factory=set)
    aliases: dict[str, str] = dataclasses.field(default_factory=dict)

    def to_implicator(self) -> gms.Implicator:
        return gms.Implicator(implications=self.implications, aliases=self.aliases)


class TagActionsObject:
    """Extract tag actions from one, unified object format.

    Tag actions without field information are assigned to the default tag
    fields.
    """

    def __init__(
        self,
        obj: object | None = None,
        default_tag_fields: Iterable[str] | None = None,
        extr: util.ObjectExtractor | None = None,
    ) -> None:
        self.default_tag_fields = frozenset(default_tag_fields or [])
        # A pool is the set of tag actions that apply to a given set of fields
        self._pools: dict[frozenset[str], _TagActionsContainer] = {}
        # A field's spec is the set of pools that apply to a given field
        # For each pair x:P, P is the set of pools that contain field x.
        self._field_spec: defaultdict[str, set[frozenset[str]]] = defaultdict(set)
        self.update(obj or {}, extr=extr)

    def read_file(self, filename: StrPath, file_format: str | None = None) -> None:
        """Read *filename* and parse tag actions based on its file extension.

        ``*.toml`` files will be parsed as TOML. Anything else will be parsed
        as JSON.

        Or, force parsing as JSON if *file_format* == "json".
        """
        path = Path(filename)
        load = util.load_from_json
        if path.match("*.toml") and file_format != "json":
            load = util.load_from_toml
        log.debug("Loading TagActionsObject from file: %s", filename)
        obj = load(path)
        self.update(obj, extr=util.ObjectExtractor(source=str(path)))

    def update(self, obj: object, extr: util.ObjectExtractor | None = None) -> None:
        self.extr = extr or util.ObjectExtractor()
        obj = self.extr.dict(obj)
        if not obj:
            return
        dests = self._parse_fields(obj)
        for dest, table_name in dests.items():
            if table_name is None:
                cm = contextlib.nullcontext(obj)
            else:
                cm = self.extr.get(obj, table_name, default=None)
            with cm as table:
                if not table:
                    self.extr.warn("Table not found with name: %s", table_name)
                    continue
                for field in dest:
                    self._field_spec[field].add(dest)
                tac = self._pools.setdefault(dest, _TagActionsContainer(fields=dest))
                tac.aliases.update(self._parse_aliases(table))
                tac.implications.update(self._parse_implications(table))

    def _parse_fields(self, obj: Mapping) -> dict[frozenset[str], str | None]:
        dests: dict[frozenset[str], str | None] = {}
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

    def _parse_aliases(self, obj: Mapping) -> Iterator[tuple[str, str]]:
        for key, value in self.extr.get_items(obj, "aliases"):
            yield str(key), str(value)

    def _parse_implications(self, obj: Mapping) -> Iterator[gms.RegularImplication]:
        yield from self._parse_regulars(obj)
        with self.extr.get_dict(obj, "descriptors") as table:
            yield from self._parse_descriptors(table)

    def _parse_regulars(self, obj: Mapping) -> Iterator[gms.RegularImplication]:
        for key, value in self.extr.get_items(obj, "implications"):
            yield gms.RegularImplication(antecedent=str(key), consequent=str(value))
        for key, value in self.extr.get_items(obj, "multi-implications"):
            antecedent = str(key)
            for consequent in self.extr.list(value):
                yield gms.RegularImplication(
                    antecedent=antecedent, consequent=str(consequent)
                )

    def _parse_descriptors(self, table: Mapping) -> Iterator[gms.RegularImplication]:
        symbols: WordMultiplier[str] = WordMultiplier()
        for name, words in self.extr.get_items(table, "sets"):
            symbols.add_set(name, self.extr.list(words))
        for name, elements in self.extr.get_items(table, "unions"):
            if name in symbols:
                self.extr.warn("Over-writing set name with union: %s", name)
            union_elements = self.extr.list(elements)
            try:
                symbols.add_union(name, *union_elements)
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

    def _make_implicator(self, spec: AbstractSet[frozenset[str]]) -> gms.Implicator:
        implic = gms.Implicator()
        alias_maps: list[dict[str, str]] = []
        for pool in spec:
            data = self._pools[pool]
            if data.aliases:
                alias_maps.append(data.aliases)
            for impl in data.implications:
                implic.add(impl)
        # Put the larger maps first in the lookup sequence.
        alias_maps.sort(key=len)
        implic.aliases = ChainMap(*alias_maps)
        return implic

    def get_implicator(self, fieldname: str | None = None) -> gms.Implicator:
        """Return the Implicator for a single field *fieldname*.

        If *fieldname* is ``None`` then return the Implicator for the default
        tag fields.
        """
        if fieldname is None:
            return self._pools[self.default_tag_fields].to_implicator()
        spec = self._field_spec[fieldname]
        return self._make_implicator(spec)

    def _spec_fields(self) -> defaultdict[frozenset[frozenset[str]], set[str]]:
        # Group fields that have the same 'spec'
        # (the set of pools that apply to them).
        # If two or more fields have the same spec, they can share the same
        # Implicator.
        spec_fields: defaultdict[frozenset[frozenset[str]], set[str]] = defaultdict(set)
        for field, spec in self._field_spec.items():
            spec_fields[frozenset(spec)].add(field)
        return spec_fields

    def implicators(self) -> Iterator[tuple[set[str], gms.Implicator]]:
        for spec, fields in self._spec_fields().items():
            yield fields, self._make_implicator(spec)


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


def check_mapping(obj: object, default: type[Mapping] = dict) -> Mapping:
    """
    Return *obj* if it is a mapping. Otherwise return an empty instance of
    *default*.
    """
    if not isinstance(obj, Mapping):
        log.error("Decoded file was not mapping")
        return default()
    return obj


def get_implications(filename: StrPath) -> frozenset[gms.BaseImplication]:
    """Read *filename* and parse implications based on its file extension."""
    extensions = ("dat", "txt", "asc", "list")
    path = Path(filename)
    if path.match("*.json"):
        data = check_mapping(util.load_from_json(path))
        return frozenset(
            gms.RegularImplication(str(k), str(v)) for k, v in data.items()
        )
    if any(path.match(f"*.{ext}") for ext in extensions):
        text = path.read_text(encoding="utf-8")
        return frozenset(
            gms.DescriptorImplication(desc) for desc in gms.split_on_whitespace(text)
        )
    log.warning(
        "Implications file exists but does not match known file extensions: %s",
        filename,
    )
    return frozenset()


def get_aliases(filename: StrOrBytesPath) -> dict[str, str]:
    data = check_mapping(util.load_from_json(filename))
    return {str(alias): str(tag) for alias, tag in data.items()}


def get_tags_from_file(*filepaths: StrPath) -> gms.TagSet:
    """
    Merge (union) whitespaced-separated tags from files in *filepaths* into one
    ``TagSet``.
    """
    tags = gms.TagSet()
    for path in filepaths:
        text = Path(path).read_text(encoding="utf-8")
        tags.update(gms.TagSet.from_tagstring(text))
    return tags


def validate_tag_actions(implicator: gms.Implicator) -> int:
    """Validate *implicator*, and return number of errors found."""
    errors = 0
    # For alias error events, log all in debug output, but log only the
    # first example in error output.
    if ta_events := implicator.validate_aliases_not_aliased():
        log.debug(ta_events)
        log.error(
            "Cannot alias a tag to a tag that is itself aliased: %s",
            " -> ".join(ta_events[0]),
        )
        log.error(
            "Found %d instance%s of transitive aliases",
            len(ta_events),
            "" if len(ta_events) == 1 else "s",
        )
        errors += len(ta_events)
    if ai_events := implicator.validate_implications_not_aliased():
        log.debug(ai_events)
        log.error(
            "Tags in implication must not be aliased to another tag: "
            "'%s' implies '%s', but '%s' is aliased to '%s'",
            ai_events[0].implication.antecedent,
            ai_events[0].implication.consequent,
            ai_events[0].antecedent,
            ai_events[0].consequent,
        )
        log.error(
            "Found %d instance%s where tags in implication were aliased",
            len(ai_events),
            "" if len(ai_events) == 1 else "s",
        )
        errors += len(ai_events)
    if cycle := implicator.graph.find_cycle():
        log.error(
            "Tag implication cannot create a circular relation with "
            "another tag implication: %s",
            " -> ".join(cycle),
        )
        log.info("More circular relations may exist in the implication graph")
        errors += 1
    return errors


def traverse_fs(root: Path, *, leaves_only: bool = False) -> Iterator[tuple[Path, int]]:
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


def traverse_main(
    root: Path, path_field: str, count_field: str, *, leaves_only: bool = False
) -> Iterator[gms.Gallery]:
    for path, count in traverse_fs(root, leaves_only=leaves_only):
        path_value = path.relative_to(root)
        yield gms.Gallery({path_field: path_value, count_field: count})
