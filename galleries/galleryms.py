# galleryms.py
#
"""Gallery management system"""

from __future__ import annotations

import fnmatch
import heapq
import itertools
import json
import math
import operator
import re
import warnings
from abc import ABC, abstractmethod
from collections import Counter, defaultdict
from collections.abc import (
    Collection,
    Iterable,
    Iterator,
    Mapping,
    MutableMapping,
    Sequence,
)
from operator import itemgetter
from pathlib import Path
from textwrap import TextWrapper
from typing import IO, Any, Callable, Dict, Optional, Set, TypeVar, Union

T = TypeVar("T")
_Comparable = TypeVar("_Comparable", int, float)
StrPath = Union[str, Path]
_Real = Union[float, int]
TS = TypeVar("TS", bound="TagSet")
Table = TypeVar("Table", bound="OverlapTable")


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

    def apply_implications(self, implications: Collection[BaseImplication]) -> None:
        """Update with *implications*."""
        current_tags = self
        while implications:
            new_tags = TagSet()
            for tag in current_tags:
                for implication in implications:
                    if match := implication.match(tag):
                        new_tags.add(match)
            if not new_tags:
                # No new tags implied. Exit.
                break
            self.update(new_tags)
            # Crucially, repeat the implication process with only the set
            # populated on the previous iteration.
            current_tags = new_tags


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

    def check_folder(self, field: str, cwd: StrPath = ".") -> Path:
        """Check if *field* contains the name of a folder that exists.

        The folder name must be a path relative to *cwd*.

        Raise ``FileNotFoundError`` if the path does not exist.
        Raise ``NotADirectoryError`` if the path does exist, but is not a
        directory.
        Otherwise return the ``Path``.
        """
        name = self[field]
        path = Path(cwd, name)
        if not path.exists():
            raise FileNotFoundError(cwd, name)
        if not path.is_dir():
            raise NotADirectoryError(cwd, name)
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


class SearchTerm(ABC):
    """Base class for a search term that can match galleries"""

    fields: list[str] = []

    @abstractmethod
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


class TagSearchTerm(SearchTerm):
    """Base class for a search term that matches tags"""

    def __init__(self, word: str, *fields: str) -> None:
        self.word = word
        self.fields = list(fields)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.word!r}, *{self.fields!r})"

    def tagsets(
        self, gallery: Gallery, cache: Optional[MutableMapping[str, Any]] = None
    ) -> Iterator[TagSet]:
        cache = cache or {}
        for fieldname in self.fields:
            yield cache.setdefault(fieldname, gallery.normalize_tags(fieldname))


class WholeSearchTerm(TagSearchTerm):
    """Search term that matches tags in their entirety

    >>> term = WholeSearchTerm("tok1", "Tags")
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

    >>> term = WildcardSearchTerm("tok*", "Tags")
    >>> bool(term.match(Gallery(Tags="tok1")))
    True
    """

    def __init__(self, word: str, *fields: str) -> None:
        super().__init__(word, *fields)
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

    >>> term = NumericCondition(operator.gt, 3, "Count")
    >>> term.match(Gallery(Count="4"))
    True
    """

    def __init__(
        self, comp_func: Callable[[_Real, _Real], Any], argument: _Real, *fields: str
    ) -> None:
        self.comp_func = comp_func
        self.argument = argument
        self.fields = list(fields)

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}"
            f"({self.comp_func!r}, {self.argument!r}, *{self.fields!r})"
        )

    def match(
        self, gallery: Gallery, cache: Optional[MutableMapping[str, Any]] = None
    ) -> bool:
        cache = cache or {}
        values: list[float] = []
        for fieldname in self.fields:
            try:
                values.append(float(cache.setdefault(fieldname, gallery[fieldname])))
            except ValueError:
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
    Query(conjuncts=[WholeSearchTerm('tok1', *['TagField1'])])
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

    def __init__(self, default_tag_fields: Optional[Sequence[str]] = None) -> None:
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

    def parse_args(self, args: Sequence[str]) -> Query:
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
                return WildcardSearchTerm(word, *fields), logical_operator
            return WholeSearchTerm(word, *fields), logical_operator
        raise ValueError


class BaseImplication(ABC):
    @abstractmethod
    def match(self, tag: str) -> Optional[str]:
        pass


class DescriptorImplication(BaseImplication):
    """Store a descriptor implication.

    Argument *word* is the descriptor in a tag. If match encounters a string
    matching ``^{word}_(.+)`` then it will return the bit matched by ``(.+)``,
    that is the thing in the tag that the descriptor is describing.

    >>> DescriptorImplication("green").match("green_shirt")
    'shirt'
    """

    def __init__(self, word: str) -> None:
        self.word = word
        self.pattern = re.compile(f"\\A{word}_(.+)")

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.word!r})"

    def match(self, tag: str) -> Optional[str]:
        """Return tag string matched after the descriptor or None."""
        if match := self.pattern.search(tag):
            return match.group(1)
        return None


class RegularImplication(BaseImplication):
    """Store a regular implication.

    *antecedent* implies *consequent*.
    """

    def __init__(self, antecedent: str, consequent: str) -> None:
        self.antecedent = antecedent
        self.consequent = consequent

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
        # Create TextWrapper objects for fields with known max width.
        # _wrappers is NOT ordered like field_fmts is.
        self._wrappers = {
            field: TextWrapper(width=fmt.width)
            for field, fmt in self.field_fmts.items()
            if fmt.width != FieldFormat.REMAINING_SPACE
        }

    def tabulate(self, rows: Iterable[dict[str, Any]]) -> Iterator[str]:
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
                    new_row[field] = self._wrappers[field].wrap(text)
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
                self._wrappers[field] = TextWrapper(width=field_size)
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
                    self._wrappers[field] = TextWrapper(width=width)

        # Wrap REM: Rewrap everything
        for row in wrapped_rows:
            for field in sizes:
                cell = row[field]
                if isinstance(cell, str):
                    row[field] = self._wrappers[field].wrap(cell)

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


class OverlapTable:
    """2D hash table of overlap between tag pairs

    Methods allow accessing overlap values, as well as calculating similarity
    metric. Two tags are similar if they have nearly the same set of
    galleries, and nearly the same size.

    The table can also be accessed directly via the table attribute, like so:
    >>> table = OverlapTable({'a', 'b'}, {'b', 'c'})
    >>> table.table['a']['b']
    1

    Other attributes:
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
    # i and j must be different. table[i][i] is not calculated.
    #
    # Similarity is calculated using cosine similarity, which is defined as
    # the number of items two sets A and B have in common, divided by
    # sqrt(||A|| * ||B||), where ||A|| is the size of A. The sqrt of the sizes
    # can be thought of as a normalizing factor, to normalize the number of
    # galleries in common to a 0.0 - 1.0 range.

    def __init__(self, *sets: TagSet) -> None:
        self.n_sets: int = 0
        self.counter: Counter[str] = Counter()
        self.table: defaultdict[str, dict[str, int]] = defaultdict()
        self.update(*sets)

    def update(self, *sets: TagSet) -> None:
        """Update the table with new sets of tags.

        This is the only method to edit the table.
        """
        self.n_sets += len(sets)
        self.counter.update(itertools.chain.from_iterable(sets))
        new_tags = frozenset(itertools.chain.from_iterable(sets))
        # Open the table for creating new entries.
        self.table.default_factory = dict
        for tag_x, tag_y in itertools.combinations(new_tags, 2):
            self.table[tag_x].setdefault(tag_y, 0)
            self.table[tag_y].setdefault(tag_x, 0)
            for tag_set in sets:
                if tag_x in tag_set and tag_y in tag_set:
                    self.table[tag_x][tag_y] += 1
                    self.table[tag_y][tag_x] += 1
        # Lock down the table. Subscript access with a bad tag will now raise
        # KeyError rather than create a new entry.
        self.table.default_factory = None

    # BINARY METHODS

    def get(self, x: str, y: str, /) -> int:
        """Get the number of overlaps between *x* and *y*."""
        try:
            return self.table[x][y]
        except KeyError:
            if x == y:
                if diagonal := self.counter.get(x):
                    return diagonal
            raise

    def similarity(self, x: str, y: str, /) -> float:
        """Calculate similarity between two tags *x* and *y*.

        Inversely, distance(x,y) is equal to 1 - similarity(x,y).
        If *x* equals *y*, then result is 1.0.
        """
        # cosine similarity(tag1, tag2) =
        #     {{tag1 tag2}} / sqrt({{tag1}} * {{tag2}})
        return self.get(x, y) / math.sqrt(self.counter[x] * self.counter[y])

    # UNARY METHODS

    def __contains__(self, tag: str) -> bool:
        return tag in self.counter

    def overlaps(self, tag: str) -> Iterator[tuple[str, int]]:
        """
        Yield the tags that *tag* overlaps with and their number of overlaps.
        """
        # Trigger KeyError
        items = self.table[tag].items()
        yield (tag, self.counter[tag])
        yield from ((key, value) for key, value in items if value > 0)

    def similarities(self, tag: str) -> Iterator[tuple[str, float]]:
        """Calculate similarity between *tag* and every other tag."""
        # Trigger KeyError
        items = self.table[tag].items()
        yield (tag, 1.0)
        for key, value in items:
            if value > 0.0:
                yield key, self.similarity(tag, key)

    def similar_tags(
        self, tag: str, n: Optional[int] = None
    ) -> list[tuple[str, float]]:
        """
        List the *n* most similar tags to *tag* and their similarity values
        from the most similar to the least, not including *tag* itself. If *n*
        is None, then list all tags.
        """
        # Skip tag itself
        sim = itertools.islice(self.similarities(tag), 1, None)
        return most_common(sim, n)

    # NULLARY METHODS

    def __len__(self) -> int:
        return len(self.counter)

    def __iter__(self) -> Iterator[str]:
        return iter(self.counter)

    def pairs(self) -> Iterator[tuple[str, str]]:
        """Iterate over all unique tag combinations."""
        return itertools.combinations(self.counter, 2)

    def pairs_overlaps(self) -> Iterator[tuple[tuple[str, str], int]]:
        """Iterate over the table.

        Yield ((x, y), table[x][y]) for every unique pair.
        """
        for x, y in self.pairs():
            yield (x, y), self.table[x][y]

    def frequent_overlaps(
        self, n: Optional[int] = None
    ) -> list[tuple[tuple[str, str], int]]:
        """
        List the *n* most likely different tag pairs to overlap and their
        number of overlaps. If *n* is None, then list all tag pairs.
        """
        return most_common(self.pairs_overlaps(), n)

    # METHODS FOR JSON SERIALIZATION

    def _to_dict(self) -> dict:
        """Convert self's data attributes to an equivalent dictionary.

        This form can be easily serialized by ``json.JSONEncoder``.
        """
        return {attr: getattr(self, attr) for attr in ("n_sets", "counter", "table")}

    def to_json_string(self, **kwds: Any) -> str:
        """Serialize the object to a JSON formatted string."""
        return json.dumps(self._to_dict(), **kwds)

    def to_json_stream(self, file: IO[str], **kwds: Any) -> None:
        """Serialize the object as a JSON formatted stream to fp."""
        return json.dump(self._to_dict(), file, **kwds)

    @classmethod
    def from_json(cls: type[Table], obj: dict) -> Table:
        """
        Reconstruct the object from *obj*, a dictionary containing the
        object's data attributes.
        """
        new_table = cls()
        new_table.n_sets = obj["n_sets"]
        new_table.counter = Counter(obj["counter"])
        new_table.table = defaultdict(None, obj["table"])
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


# Sort by second item in sequence (index=1)
def most_common(
    it: Iterable[tuple[T, _Comparable]], n: Optional[int] = None
) -> list[tuple[T, _Comparable]]:
    n = 0 if n is None else n
    if n <= 0:
        commons = sorted(it, key=itemgetter(1), reverse=True)
        if n < 0:
            return commons[:n]
        return commons
    return heapq.nlargest(n, it, key=itemgetter(1))
