# galleryms.py
#
"""Gallery management system"""

from __future__ import annotations

import abc
import csv
import dataclasses
import fnmatch
import heapq
import itertools
import json
import math
import operator
import re
import textwrap
import warnings
from collections import ChainMap, Counter, defaultdict
from collections.abc import (
    Hashable,
    Iterable,
    Iterator,
    Mapping,
    MutableMapping,
    MutableSequence,
    MutableSet,
    Sequence,
)
from pathlib import Path
from typing import (
    IO,
    Any,
    Callable,
    Collection,
    Dict,
    Generic,
    NamedTuple,
    NewType,
    Optional,
    Set,
    Tuple,
    TypeVar,
    Union,
)

T = TypeVar("T")
H = TypeVar("H", bound=Hashable)
_Comparable = TypeVar("_Comparable", int, float)
StrPath = Union[str, Path]
_Real = Union[float, int]
TS = TypeVar("TS", bound="TagSet")
Table = TypeVar("Table", bound="OverlapTable")
TransitiveAliases = NewType("TransitiveAliases", Tuple[str, str, str])


class AliasedImplication(NamedTuple):
    implication: RegularImplication
    antecedent: str
    consequent: str


class ImplicationGraph:
    """Directed acyclic graph of tag implications

    >>> graph = ImplicationGraph({'a': {'b'}, 'b': {'c'}})
    >>> sorted(graph.descendants_of('a'))
    ['b', 'c']
    >>> tagset = TagSet(['d'])
    >>> graph.join_descendants(tagset, 'a')
    >>> sorted(tagset)
    ['a', 'b', 'c', 'd']
    """

    def __init__(self, graph: Optional[Mapping[str, Iterable[str]]] = None) -> None:
        self.graph: defaultdict[str, TagSet] = defaultdict(TagSet)
        if graph is not None:
            for node, consequents in graph.items():
                self.add_edge(node, *consequents)

    def add_edge(self, antecedent: str, *consequent: str) -> None:
        self.graph[antecedent].update(consequent)

    def _traverse(
        self, node: str, stack: MutableSequence[str], seen: MutableSet[str]
    ) -> Optional[str]:
        """Recursive function to visit each node in the graph"""
        # Mark current node as visited and add to recursion stack
        seen.add(node)
        stack.append(node)
        # If any neighbor is visited and in recursion stack
        # then graph is cyclic
        for neighbor in self.graph[node]:
            if neighbor not in seen:
                if cycle_0 := self._traverse(neighbor, stack, seen):
                    return cycle_0
            elif neighbor in stack:
                return neighbor
        # Pop node from stack -- its descendants are free of cycles
        stack.pop()
        return None

    def find_cycle(self) -> Optional[list[str]]:
        """Find cycles in the graph. Return ``None`` if no cycles found.

        If multiple cycles exist, only one will be returned.
        The cycle is returned as a list of nodes, such that each node is, in
        the graph, an immediate predecessor of the next node in the list.
        The first and last node in the list will be the same, to make it clear
        that it is cyclic.
        """
        # We don't expect to exceed max recursion depth
        nodes_seen = TagSet()
        recursion_stack: list[str] = []
        for node in list(self.graph):
            if node not in nodes_seen:
                if cycle_0 := self._traverse(node, recursion_stack, nodes_seen):
                    cycle = recursion_stack[recursion_stack.index(cycle_0) :]
                    return cycle + [cycle_0]
        return None

    def tags_implied_by(self, tag: str) -> TagSet:
        """Get children of *tag* from graph without creating default entry."""
        return self.graph.get(tag, TagSet())

    def descendants_of(self, tag: str) -> TagSet:
        current_tags = self.tags_implied_by(tag)
        descendants = current_tags
        while current_tags:
            new_tags = TagSet()
            for implied_tag in current_tags:
                new_tags.update(self.tags_implied_by(implied_tag))
            descendants.update(new_tags)
            current_tags = new_tags
        return descendants

    def join_descendants(self, tagset: TagSet, tag: str) -> None:
        """Add *tag* and its descendants to *tagset*."""
        tagset.add(tag)
        for neighbor in self.graph[tag]:
            if neighbor not in tagset:
                self.join_descendants(tagset, neighbor)


class Implicator(ImplicationGraph):
    """Collection of tag implications + tag aliases"""

    def __init__(
        self,
        implications: Optional[Iterable[RegularImplication]] = None,
        aliases: Optional[MutableMapping[str, str]] = None,
    ) -> None:
        super().__init__()
        self.implications = set(implications or [])
        self.aliases = ChainMap(aliases or {})
        if implications is not None:
            for implication in implications:
                self.add(implication)

    def add(self, implication: RegularImplication) -> None:
        self.add_edge(implication.antecedent, implication.consequent)
        self.implications.add(implication)

    def validate_implications_not_aliased(
        self,
    ) -> list[AliasedImplication]:
        """Find instances where tags in implication have been aliased.

        Return a list of AliasedImplication objects, each of which contains
        an implication, a member tag of which has been aliased, and the two
        tags in the tag alias.
        Return an empty list, if none found.
        """
        events: list[AliasedImplication] = []
        for implication in self.implications:
            if tag := self.aliases.get(implication.antecedent):
                events.append(
                    AliasedImplication(implication, implication.antecedent, tag)
                )
            if tag := self.aliases.get(implication.consequent):
                events.append(
                    AliasedImplication(implication, implication.consequent, tag)
                )
        return events

    def validate_aliases_not_aliased(self) -> list[TransitiveAliases]:
        """Find instances in aliases where a -> b && b -> c.

        Return a list of 3-tuples, of which each element is a tag in the
        transitive relation, in the order a -> b -> c.
        Return an empty list, if none found.
        """
        events: list[TransitiveAliases] = []
        for alias, tag in self.aliases.items():
            if other_tag := self.aliases.get(tag):
                events.append(TransitiveAliases((alias, tag, other_tag)))
        return events

    def implicate(self, tagset: TagSet) -> None:
        tagset.apply_aliases(self.aliases)
        for tag in list(tagset):
            self.join_descendants(tagset, tag)


class TagSet(Set[str]):
    """A set of tags

    >>> tagset = TagSet.from_tagstring("tok1 tok2")
    >>> implication = RegularImplication("tok1", "tok5")
    >>> tagset.apply_implications([implication])
    >>> str(tagset)
    'tok1 tok2 tok5'
    """

    @classmethod
    def from_tagstring(cls: type[TS], tagstring: str) -> TS:
        """Construct from string with whitespace-separated tags"""
        return cls(tagstring.lower().split())

    def __str__(self) -> str:
        return " ".join(sorted(self))

    def implied_tags(self: TS, implications: Iterable[BaseImplication]) -> TS:
        consequents = type(self)()
        for implication in implications:
            for tag in self:
                if implied := implication.match(tag):
                    consequents.add(implied)
                    break
        return consequents

    def aliased_tags(self: TS, aliases: Mapping[str, str]) -> TS:
        """Return a new set with aliased tags replaced by real tags."""
        tagset = type(self)(self.copy())
        tagset.apply_aliases(aliases)
        return tagset

    def apply_implications(self, implications: Iterable[BaseImplication]) -> None:
        """Update with *implications*."""
        current_tags = self
        while implications:
            new_tags = current_tags.implied_tags(implications)
            if not new_tags:
                # No new tags implied. Exit.
                break
            self.update(new_tags)
            # Crucially, repeat the implication process with only the set
            # populated on the previous iteration.
            current_tags = new_tags

    def apply_aliases(self, aliases: Mapping[str, str]) -> None:
        """Update with *aliases*, translating tags from key to value."""
        for alias, tag in aliases.items():
            if alias in self:
                self.remove(alias)
                self.add(tag)


class Gallery(Dict[str, Any]):
    """Represent one row of the database."""

    def merge_tags(self, *fields: str) -> TagSet:
        """Return the tags from *fields* as a single ``TagSet``."""
        tags = TagSet()
        for field in fields:
            tags.update(self.normalize_tags(field))
        return tags

    def normalize_tags(self, field: str) -> TagSet:
        """Return the ``TagSet`` from *field*."""
        if not isinstance(self[field], TagSet):
            return TagSet.from_tagstring(self[field])
        return self[field]

    def get_folder(self, field: str, cwd: StrPath = ".") -> Path:
        """Get the ``Path`` value from *field* relative to *cwd*."""
        name = self[field]
        return Path(cwd, name)

    def check_folder(self, field: str, cwd: StrPath = ".") -> Path:
        """Check if *field* contains the name of a folder that exists.

        The folder name must be a path relative to *cwd*.

        Raise ``FileNotFoundError`` if the path does not exist.
        Raise ``NotADirectoryError`` if the path does exist, but is not a
        directory.
        Otherwise return the ``Path``.
        """
        path = self.get_folder(field, cwd=cwd)
        if not path.exists():
            raise FileNotFoundError(path)
        if not path.is_dir():
            raise NotADirectoryError(path)
        return path

    def update_count(self, field: str, folder_path: Path) -> None:
        """Update *field* with number of files in *folder_path*.

        The count does not include directories and hidden files (files with
        names that start with '.').
        """
        self[field] = sum(
            1
            for file in folder_path.iterdir()
            if not file.is_dir() and not file.name.startswith(".")
        )


class Reader(Iterable[Gallery]):
    def __init__(self, reader: Optional[csv.DictReader] = None) -> None:
        if reader is None:
            self._reader = ()
            self.fieldnames = ()
        else:
            self._reader = reader
            self.fieldnames = reader.fieldnames

    def __iter__(self) -> Iterator[Gallery]:
        for row in self._reader:
            yield Gallery(row)


class SearchTerm(abc.ABC):
    """Base class for a search term that can match galleries"""

    fields: list[str] = []

    @abc.abstractmethod
    def match(
        self, gallery: Gallery, cache: Optional[MutableMapping[str, Any]] = None
    ) -> Any:
        """Return a truthy value if *gallery* is matched by this term.

        Optional *cache* is a mapping of fields and field values that have
        already been parsed by a ``SearchTerm.match`` method. *cache* will be
        updated if a value is parsed. *gallery* will not be modified.
        """

    def disambiguate_fields(self, fieldnames: Sequence[str]) -> None:
        """Disambiguate this term's ``fields`` between *fieldnames*.

        If a field name in ``fields`` starts with the same letters as a field
        name in *fieldnames*, change this term so it refers unambiguously to
        that name.

        Raise ``ValueError`` if this term does not refer to any of the field
        names in *fieldnames*.
        Raise ``ValueError`` if there are multiple possible field names in
        *fieldnames*.
        """
        disambiguated = []
        for field in self.fields:
            specifier = field.casefold()
            candidates = [
                fieldname
                for fieldname in fieldnames
                if fieldname.casefold().startswith(specifier)
            ]
            if len(candidates) < 1:
                raise ValueError(f"No field names starting with '{field}'")
            if len(candidates) > 1:
                raise ValueError(f"Field '{field}' is ambiguous between {candidates}")
            disambiguated.append(candidates[0])
        self.fields = disambiguated

    @staticmethod
    def _rectify_fields(arg: Optional[Union[str, Iterable[str]]]) -> list[str]:
        if isinstance(arg, str):
            arg = [arg]
        return list(arg) if arg is not None else []


class TagSearchTerm(SearchTerm):
    """Base class for a search term that matches tags"""

    def __init__(
        self, word: str, fields: Optional[Union[str, Iterable[str]]] = None
    ) -> None:
        self.word = word
        self.fields = self._rectify_fields(fields)

    def __repr__(self) -> str:
        fields = f", fields={self.fields!r}" if self.fields else ""
        return f"{type(self).__name__}({self.word!r}{fields})"

    def tagsets(
        self, gallery: Gallery, cache: Optional[MutableMapping[str, Any]] = None
    ) -> Iterator[TagSet]:
        cache = cache or {}
        for fieldname in self.fields:
            yield cache.setdefault(fieldname, gallery.normalize_tags(fieldname))


class WholeSearchTerm(TagSearchTerm):
    """Search term that matches tags in their entirety

    >>> term = WholeSearchTerm("tok1", ["Tags"])
    >>> bool(term.match(Gallery(Tags="tok2")))
    False
    >>> bool(term.match(Gallery(Tags="tok1 tok2")))
    True
    """

    def match(
        self, gallery: Gallery, cache: Optional[MutableMapping[str, Any]] = None
    ) -> Any:
        for tagset in self.tagsets(gallery, cache):
            if self.word in tagset:
                return self.word
        return None


class WildcardSearchTerm(TagSearchTerm):
    """Search term that matches tags in part, using wildcard characters

    Uses :module:`fnmatch`, which supports Unix shell-style wildcards

    >>> term = WildcardSearchTerm("tok*", ["Tags"])
    >>> bool(term.match(Gallery(Tags="tok1")))
    True
    """

    def __init__(
        self, word: str, fields: Optional[Union[str, Iterable[str]]] = None
    ) -> None:
        super().__init__(word, fields=fields)
        self.regex = re.compile(fnmatch.translate(word))

    def match(
        self, gallery: Gallery, cache: Optional[MutableMapping[str, Any]] = None
    ) -> Any:
        for tagset in self.tagsets(gallery, cache):
            for tag in tagset:
                if match := self.regex.match(tag):
                    return match
        return None


class NumericCondition(SearchTerm):
    """Search term that can compare numbers

    If a field value cannot be converted to a ``float``, the gallery will not
    be matched.

    >>> term = NumericCondition(operator.gt, 3, fields=["Count"])
    >>> term.match(Gallery(Count="4"))
    True
    """

    def __init__(
        self,
        comp_func: Callable[[_Real, _Real], Any],
        argument: _Real,
        fields: Optional[Union[str, Iterable[str]]] = None,
    ) -> None:
        self.comp_func = comp_func
        self.argument = argument
        self.fields = self._rectify_fields(fields)

    def __repr__(self) -> str:
        parameters = [repr(self.comp_func), repr(self.argument)]
        if self.fields:
            parameters.append(f"fields={self.fields!r}")
        return f"{type(self).__name__}({', '.join(parameters)})"

    def match(
        self, gallery: Gallery, cache: Optional[MutableMapping[str, Any]] = None
    ) -> bool:
        cache = cache or {}
        values: list[float] = []
        for fieldname in self.fields:
            try:
                value = cache.setdefault(fieldname, gallery[fieldname])
                values.append(float(value))  # type: ignore
            except (ValueError, TypeError):
                # Rows with null or invalid values _will_ be excluded from
                # results
                return False
        return any(self.comp_func(value, self.argument) for value in values)


class Query:
    """Collection of ``SearchTerm``s grouped by truth function

    For a query to match a gallery:

      - All *conjuncts* must match.
      - Any *negations* must not match.
      - If any *disjuncts*, at least one must match.

    If a query is empty, it matches any gallery.
    """

    def __init__(
        self,
        conjuncts: Optional[Iterable[SearchTerm]] = None,
        negations: Optional[Iterable[SearchTerm]] = None,
        disjuncts: Optional[Iterable[SearchTerm]] = None,
    ) -> None:
        self.conjuncts = list(conjuncts or [])
        self.negations = list(negations or [])
        self.disjuncts = list(disjuncts or [])

    def __repr__(self) -> str:
        attrs = ", ".join(
            f"{name}={value!r}"
            for name in ("conjuncts", "negations", "disjuncts")
            if (value := getattr(self, name))
        )
        return f"{type(self).__name__}({attrs})"

    def __bool__(self) -> bool:
        return bool(self.conjuncts or self.negations or self.disjuncts)

    def match(self, gallery: Gallery) -> bool:
        # data_cache will be modified as field data is parsed
        data_cache: dict[str, Any] = {}
        conjuncts = [t.match(gallery, data_cache) for t in self.conjuncts]
        negations = [t.match(gallery, data_cache) for t in self.negations]
        disjuncts = [t.match(gallery, data_cache) for t in self.disjuncts]
        return (
            all(conjuncts)
            and not any(negations)
            and (any(disjuncts) or not disjuncts)
            #                   ^
            # If disjuncts is merely empty, still return True
        )

    def all_terms(self) -> Iterator[SearchTerm]:
        yield from self.conjuncts
        yield from self.negations
        yield from self.disjuncts


class ArgumentParser:
    """Parse argument tokens into matchable search terms.

    If provided, *default_tag_fields* will be returned with ``TagSearchTerm``s
    that do not have their own field specifiers.

    >>> ap = ArgumentParser(["TagField1"])
    >>> ap.parse_args(["tok1"])
    Query(conjuncts=[WholeSearchTerm('tok1', fields=['TagField1'])])
    """

    fieldname_chars = r"a-z0-9_\-"
    tag_chars = r"a-z0-9_\-"
    wildcard = "%"
    not_operator = "~"
    or_operator = "+"
    field_tag_sep = ":"
    field_number_sep = "="
    relationals = {
        None: operator.eq,
        "ne": operator.ne,
        "gt": operator.gt,
        "lt": operator.lt,
        "ge": operator.ge,
        "le": operator.le,
    }

    def __init__(self, default_tag_fields: Optional[Iterable[str]] = None) -> None:
        self.default_tag_fields = tuple(default_tag_fields or ())
        self.compile()

    def compile(self) -> None:
        relationals = "|".join(
            f"(?:{re.escape(exp)})" for exp in self.relationals if exp
        )
        wildcard = re.escape(self.wildcard)
        not_operator = re.escape(self.not_operator)
        or_operator = re.escape(self.or_operator)
        field_tag_sep = re.escape(self.field_tag_sep)
        field_number_sep = re.escape(self.field_number_sep)
        re_pattern = f"""
                (?P<logical_group> {not_operator}|{or_operator}) ?
                                                # logical operator
            (?: (?:
            # NUMERIC SPECIFIER
            (?P<num_field> [{self.fieldname_chars}]+){field_number_sep}
                                                # field specifier, mandatory
                (?P<relation> {relationals}) ?  # relational operator
            (?P<num> -?[0-9]+)                  # constant
            ) | (?:
            # TAG SPECIFIER
            (?:
                (?P<tag_field> [{self.fieldname_chars}]+){field_tag_sep}
            ) ?                                 # field specifier, optional
            (?P<tag> [{self.tag_chars}{wildcard}]+)
                                                # search term
            ) )
        """
        self._regex = re.compile(re_pattern, re.VERBOSE | re.IGNORECASE)

    def parse_args(self, args: Iterable[str]) -> Query:
        """Parse a series of argument tokens."""
        conjuncts, negations, disjuncts = [], [], []
        for argument in args:
            search_term, logical_operator = self.parse_argument(argument)
            if logical_operator == self.not_operator:
                negations.append(search_term)
            elif logical_operator == self.or_operator:
                disjuncts.append(search_term)
            else:
                conjuncts.append(search_term)
        return Query(conjuncts=conjuncts, negations=negations, disjuncts=disjuncts)

    def parse_argument(self, argument: str) -> tuple[SearchTerm, Optional[str]]:
        """Parse a single argument token.

        Return a ``SearchTerm`` and the string value of the token's logical
        operator if there is one.

        ``ValueError`` is raised if the token cannot be parsed.
        """
        if match := self._regex.fullmatch(argument):
            return self._parse_match_object(match)
        raise ValueError(argument)

    def _parse_match_object(self, match: re.Match) -> tuple[SearchTerm, Optional[str]]:
        logical_operator = match.group("logical_group")
        if (fieldname := match.group("num_field")) is not None:
            if (relation := match.group("relation")) is not None:
                relation = relation.casefold()
            comp_func = self.relationals[relation]
            constant = int(match.group("num"))
            return (NumericCondition(comp_func, constant, fieldname), logical_operator)
        if (word := match.group("tag")) is not None:
            fieldname = match.group("tag_field")
            fields = [fieldname] if fieldname else self.default_tag_fields
            if self.wildcard in word:
                word = word.replace(self.wildcard, "*")
                return WildcardSearchTerm(word, fields=fields), logical_operator
            return WholeSearchTerm(word, fields=fields), logical_operator
        raise ValueError


class BaseImplication(abc.ABC):
    @abc.abstractmethod
    def match(self, tag: str) -> Optional[str]:
        pass


@dataclasses.dataclass(frozen=True)
class DescriptorImplication(BaseImplication):
    """Store a descriptor implication.

    Argument *word* is the descriptor in a tag. If match encounters a string
    matching ``^{word}_(.+)`` then it will return the bit matched by ``(.+)``,
    that is the thing in the tag that the descriptor is describing.

    >>> DescriptorImplication("green").match("green_shirt")
    'shirt'
    """

    word: str
    pattern: re.Pattern = dataclasses.field(init=False, compare=False)

    def __post_init__(self):
        object.__setattr__(self, "pattern", re.compile(f"\\A{self.word}_(.+)"))

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.word!r})"

    def match(self, tag: str) -> Optional[str]:
        """Return tag string matched after the descriptor or None."""
        if match := self.pattern.search(tag):
            return match.group(1)
        return None


@dataclasses.dataclass(frozen=True)
class RegularImplication(BaseImplication):
    """Store a regular implication.

    *antecedent* implies *consequent*.
    """

    antecedent: str
    consequent: str

    def __repr__(self) -> str:
        return f"{type(self).__name__}" f"({self.antecedent!r}, {self.consequent!r})"

    def match(self, tag: str) -> Optional[str]:
        """Return consequent if string == antecedent."""
        if tag == self.antecedent:
            return self.consequent
        return None


class FieldFormat:
    """Specify output formatting for a field in a table.

    Parameters:
        width: maximum width to which column will be wrapped
            An argument with a value of FieldFormat.REMAINING_SPACE means
            the column will receive the horizontal space remaining after the
            other columns have been wrapped.
        fg: foreground color, i.e. font color
        bg: background color
        effect: text effect

    Available colors and effects are listed in FieldFormat.COLORS and
    FieldFormat.EFFECTS, respectively.
    """

    REMAINING_SPACE = REM = -1

    COLORS = {
        "": ("", ""),
        "black": ("30", "40"),
        "red": ("31", "41"),
        "green": ("32", "42"),
        "yellow": ("33", "43"),
        "blue": ("34", "44"),
        "magenta": ("35", "45"),
        "cyan": ("36", "46"),
        "white": ("37", "47"),
        "bright black": ("90", "100"),
        "grey": ("90", "100"),
        "bright red": ("91", "101"),
        "bright green": ("92", "102"),
        "bright yellow": ("93", "103"),
        "bright blue": ("94", "104"),
        "bright magenta": ("95", "105"),
        "bright cyan": ("96", "106"),
        "bright white": ("97", "107"),
    }
    EFFECTS = {
        "": "",
        "bold": "1",
        "faint": "2",
        "dim": "2",
        "italic": "3",
        "underline": "4",
        "reverse video": "7",
        "invert": "7",
    }

    def __init__(
        self, width: int, fg: str = "", bg: str = "", effect: str = ""
    ) -> None:
        self.width = width
        self._fg = fg
        self.fg = self.COLORS[fg][0]
        self._bg = bg
        self.bg = self.COLORS[bg][1]
        self._effect = effect
        try:
            self.effect = self.EFFECTS[effect]
        except KeyError:
            self.effect = str(effect)
            warnings.warn(f"using string value of argument {self.effect!r}")
        self.sgr = ";".join(s for s in (self.effect, self.fg, self.bg) if s)

    def colorize(self, lines: Iterable[str]) -> Iterator[str]:
        for line in lines:
            if not self.sgr:
                yield line
            else:
                yield f"\033[{self.sgr}m{line}\033[0m"

    def __repr__(self) -> str:
        kwargs = {"fg": self._fg, "bg": self._bg, "effect": self._effect}
        args_str = ", ".join(
            [repr(self.width)]
            + [f"{kw}={arg!r}" for kw, arg in kwargs.items() if arg != ""]
        )
        return f"{type(self).__name__}({args_str})"


class Tabulator:
    """Wrap columns of text.

    Parameters:
        field_fmts: mapping of field (column) names to a FieldFormat object
            Use integer keys if your rows data are sequences rather than
            dicts. Integer values will be interpreted as FieldFormat widths.
        total_width: all columns will fit inside this width (e.g., the width
            of your terminal window)
        padding: number of spaces between each column
        left_margin: number of spaces before the first column
        right_margin: number of spaces after the last column
    """

    def __init__(
        self,
        field_fmts: Mapping[str, FieldFormat],
        total_width: int = 80,
        padding: int = 2,
        left_margin: int = 1,
        right_margin: int = 1,
    ) -> None:
        self.field_fmts = {
            field: self._rectify_format(field_fmts[field]) for field in field_fmts
        }
        self.total_width = total_width
        self.padding = padding
        self.left_margin = left_margin
        self.right_margin = right_margin

    def _wrappers(self) -> dict[str, textwrap.TextWrapper]:
        """Create TextWrapper objects for fields with known max width.

        _wrappers is *not* ordered like field_fmts is.
        """
        return {
            field: textwrap.TextWrapper(width=fmt.width)
            for field, fmt in self.field_fmts.items()
            if fmt.width != FieldFormat.REMAINING_SPACE
        }

    def tabulate(self, rows: Iterable[Mapping[str, Any]]) -> Iterator[str]:
        """Yield one line of table at a time.

        Parameter:
            rows: an iterable of text rows
                Each text row can be: a sequence of strings (indexed by
                integer) or a mapping of field (column) names to a string
                (where order is therefore unimportant).

        Yields:
            One str for each line of resulting table
                If rows is empty, yield nothing.
        """
        wrappers = self._wrappers()

        # Wrap to max widths
        wrapped_rows: list[dict[str, Union[str, list[str]]]] = []
        for row in rows:
            new_row: dict[str, Union[str, list[str]]] = {}
            for field, fmt in self.field_fmts.items():
                text = str(row[field])
                max_width = fmt.width
                if not text:
                    new_row[field] = [text]
                    # textwrap.TextWrapper returns [] on '',
                    # not [''] as expected (Issue15510)
                elif max_width != FieldFormat.REMAINING_SPACE:
                    new_row[field] = wrappers[field].wrap(text)
                else:
                    new_row[field] = text
            # Fields not in field_fmts do not get added
            wrapped_rows.append(new_row)
        if not wrapped_rows:
            # Exit in case of empty input
            return

        # Calculate actual widths after wrapping once
        sizes: dict[str, int] = {}
        n_remaining_cols = 0
        for field, fmt in self.field_fmts.items():
            # Record the longest line in each wrapped column
            if fmt.width == FieldFormat.REMAINING_SPACE:
                sizes[field] = max(len(row[field]) for row in wrapped_rows)
                n_remaining_cols += 1
            else:
                sizes[field] = max(
                    len(val) for row in wrapped_rows for val in row[field]
                )

        # Adjust wrapper widths
        whitespace_used = (
            self.left_margin + self.right_margin + (len(sizes) - 1) * self.padding
        )
        total_used = whitespace_used + sum(sizes.values())
        if total_used <= self.total_width or n_remaining_cols <= 0:
            for field, field_size in sizes.items():
                wrappers[field] = textwrap.TextWrapper(width=field_size)
        else:
            # Assign remainder to REM
            remainder = (
                self.total_width
                - whitespace_used
                - sum(
                    size
                    for field, size in sizes.items()
                    if self.field_fmts[field].width != FieldFormat.REMAINING_SPACE
                )
            )
            rems = distribute(remainder, n_remaining_cols)
            for field in sizes:
                if self.field_fmts[field].width == FieldFormat.REMAINING_SPACE:
                    width = rems.pop(0)
                    sizes[field] = width
                    wrappers[field] = textwrap.TextWrapper(width=width)

        # Wrap REM: Rewrap everything
        for row in wrapped_rows:
            for field in sizes:
                cell = row[field]
                if isinstance(cell, str):
                    row[field] = wrappers[field].wrap(cell)

        # wrapped_rows is now List[Dict[str, List[str]]]
        # sizes contains widths of each column

        # Left justify each cell, then colorize adding 0-width characters
        for row in wrapped_rows:
            for field in row:
                fmt = self.field_fmts[field]
                row[field] = list(
                    fmt.colorize(cell.ljust(sizes[field]) for cell in row[field])
                )

        line_template = "{left_margin}{cells}{right_margin}"
        for row in wrapped_rows:
            for line in itertools.zip_longest(*row.values(), fillvalue=""):
                # It is necessary to add whitespace to empty lines
                cells = (cell.ljust(width) for width, cell in zip(sizes.values(), line))
                out = line_template.format(
                    left_margin=" " * self.left_margin,
                    cells=(" " * self.padding).join(cells),
                    right_margin=" " * self.right_margin,
                )
                yield out

    @staticmethod
    def _rectify_format(val: Any) -> FieldFormat:
        """Pass int-able values into a FieldFormat object."""
        if not isinstance(val, FieldFormat):
            # Do not catch ValueError, TypeError
            return FieldFormat(int(val))
        return val


@dataclasses.dataclass
class TagCount(Generic[H]):
    tag: H
    count: int


@dataclasses.dataclass
class SimilarityCalculator:
    """Provide a variety of similarity metrics between two tags.

    Two tags are considered similar if they have nearly the same set of
    galleries and nearly the same size.
    """

    tag_a: TagCount
    tag_b: TagCount
    overlap: int

    def cosine_similarity(self) -> float:
        """Known as the Otsuka–Ochiai coefficient"""
        return self.overlap / math.sqrt(self.tag_a.count * self.tag_b.count)

    def jaccard_index(self) -> float:
        return self.overlap / (self.tag_a.count + self.tag_b.count - self.overlap)

    def overlap_coefficient(self) -> float:
        return self.overlap / min([self.tag_a.count, self.tag_b.count])

    def frequency(self) -> float:
        """How frequently tag A occurs together with tag B"""
        return self.overlap / self.tag_a.count


class OverlapTable(Collection[H]):
    """2D hash table of overlap between tag pairs

    Methods allow accessing overlap values, i.e. the number of sets that two
    tags occur in together, as well as calculating similarity metrics.

    >>> table = OverlapTable({'a', 'b'}, {'b', 'c'})
    >>> table.get('a', 'b')
    1
    >>> table.similarity('a', 'b').jaccard_index()
    0.5

    Other properties:
        n_sets: number of input sets
        counter: counts tags in input sets

    >>> table.n_sets
    2
    >>> table.counter
    Counter({'b': 2, 'a': 1, 'c': 1})
    """

    # Poor man's version of pandas DataFrame with labels
    #
    # The table matrix is symmetrical: table[i][j] == table[j][i]. Either
    # returns the number of galleries that tags i and j have in common.

    def __init__(self, *sets: Iterable[H]) -> None:
        self._n_sets: int = 0
        self._table: defaultdict[H, Counter[H]] = defaultdict(Counter)
        self.update(*sets)

    def update(self, *sets: Iterable[H]) -> None:
        """Update the table with new sets of tags.

        This is the only method to edit the table.
        """
        for tag_set in sets:
            self._n_sets += 1
            for tag_x, tag_y in itertools.product(tag_set, repeat=2):
                self._table[tag_x][tag_y] += 1

    # BINARY METHODS

    def get(self, x: H, y: H, /) -> int:
        """Get the number of overlaps between *x* and *y*."""
        return self._table.get(x, {})[y]

    def similarity(self, x: H, y: H, /) -> SimilarityCalculator:
        tag_x = TagCount(x, self.count(x))
        tag_y = TagCount(y, self.count(y))
        return SimilarityCalculator(tag_x, tag_y, self.get(x, y))

    # UNARY METHODS

    def count(self, tag: H) -> int:
        return self.get(tag, tag)

    def __contains__(self, tag: object) -> bool:
        return tag in self._table

    def overlaps(self, tag: H) -> Iterator[tuple[H, int]]:
        """
        Yield the tags that *tag* overlaps with and their number of overlaps.
        """
        yield from self._table.get(tag, {}).items()

    def similarities(self, tag: H) -> Iterator[SimilarityCalculator]:
        tag_a = TagCount(tag, self.count(tag))
        for other_tag, overlap in self.overlaps(tag):
            tag_b = TagCount(other_tag, self._table[other_tag][other_tag])
            yield SimilarityCalculator(tag_a, tag_b, overlap)

    # NULLARY METHODS

    @property
    def n_sets(self) -> int:
        return self._n_sets

    @property
    def counter(self) -> Counter:
        return Counter({tag: counter[tag] for tag, counter in self._table.items()})

    def __len__(self) -> int:
        return len(self._table)

    def __iter__(self) -> Iterator[H]:
        return iter(self._table.keys())

    def pairs(self) -> Iterator[tuple[H, H]]:
        """Iterate over all unique tag combinations."""
        return itertools.combinations(self, 2)

    def pairs_overlaps(self) -> Iterator[tuple[tuple[H, H], int]]:
        """Iterate over the table.

        Yield ((x, y), table[x][y]) for every unique pair.
        """
        for x, y in self.pairs():
            yield (x, y), self._table[x][y]

    def frequent_overlaps(
        self, n: Optional[int] = None
    ) -> list[tuple[tuple[H, H], int]]:
        """
        List the *n* most likely different tag pairs to overlap and their
        number of overlaps. If *n* is None, then list all tag pairs.
        """
        return most_common(self.pairs_overlaps(), key=operator.itemgetter(1), n=n)

    # METHODS FOR JSON SERIALIZATION

    def _to_dict(self) -> dict:
        """Convert self's data attributes to an equivalent dictionary.

        This form can be easily serialized by ``json.JSONEncoder``.
        """
        return {attr: getattr(self, attr) for attr in ("_n_sets", "_table")}

    def to_json_string(self, **kwds: Any) -> str:
        """Serialize the object to a JSON formatted string."""
        return json.dumps(self._to_dict(), **kwds)

    def to_json_stream(self, file: IO[str], **kwds: Any) -> None:
        """Serialize the object as a JSON formatted stream to fp."""
        return json.dump(self._to_dict(), file, **kwds)

    @classmethod
    def from_json(cls: type[Table], obj: Mapping) -> Table:
        """
        Reconstruct the object from *obj*, a dictionary containing the
        object's data attributes.
        """
        new_table = cls()
        new_table._n_sets = obj["_n_sets"]
        for key, counter in obj["_table"].items():
            new_table._table[key].update(counter)
        return new_table


def distribute(n: int, k: int) -> list[int]:
    """Distribute *n* quantities to *k* quantities, one by one.

    >>> distribute(79, 4)
    [20, 20, 20, 19]
    """
    arr = [n // k for i in range(k)]
    r = n % k
    for i in range(r):
        arr[i] += 1
    assert sum(arr) == n
    return arr


def most_common(
    it: Iterable[T], key: Callable[[T], _Comparable], n: Optional[int] = None
) -> list[T]:
    n = 0 if n is None else n
    if n <= 0:
        commons = sorted(it, key=key, reverse=True)
        if n < 0:
            return commons[:n]
        return commons
    return heapq.nlargest(n, it, key=key)
