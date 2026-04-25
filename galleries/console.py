# console.py
#
"""Format output to console."""

from __future__ import annotations

import dataclasses
import itertools
import textwrap
from collections.abc import Generator, Iterable, Iterator, Mapping
from typing import TYPE_CHECKING, ClassVar, Generic, TypeVar

if TYPE_CHECKING:
    from _typeshed import ConvertibleToInt, SupportsGetItem
    from typing_extensions import Self


_IndexT = TypeVar("_IndexT", bound=str | int)


@dataclasses.dataclass
class FieldFormat:
    """Specify output formatting for a field in a table.

    Args:
        width: maximum width to which column will be wrapped.
            An argument with a value of FieldFormat.REMAINING_SPACE means
            the column will receive the horizontal space remaining after the
            other columns have been wrapped.
        sgr: ECMA-48 Select Graphic Rendition sequence.
            Sets display attributes. Several attributes can be set in the same
            sequence, separated by semicolons.
    """

    width: int
    sgr: str = ""

    REMAINING_SPACE = REM = -1

    COLORS: ClassVar[dict[str, tuple[str, str]]] = {
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
    EFFECTS: ClassVar[dict[str, str]] = {
        "": "",
        "bold": "1",
        "faint": "2",
        "dim": "2",
        "italic": "3",
        "underline": "4",
        "reverse video": "7",
        "invert": "7",
    }

    @classmethod
    def from_names(
        cls, width: int, fg: str = "", bg: str = "", effect: str = ""
    ) -> Self:
        """Construct using named colors and effects.

        Available colors and effects are listed in FieldFormat.COLORS and
        FieldFormat.EFFECTS, respectively.

        Args:
            width: same as __init__.
            fg: foreground color, i.e. font color.
            bg: background color.
            effect: text effect.
        """
        fg = cls.COLORS[fg][0]
        bg = cls.COLORS[bg][0]
        effect = cls.EFFECTS.get(effect, str(effect))
        sgr = ";".join(s for s in (fg, bg, effect) if s)
        return cls(width, sgr)

    def colorize(self, lines: Iterable[str]) -> Iterator[str]:
        for line in lines:
            if not self.sgr:
                yield line
            else:
                yield f"\033[{self.sgr}m{line}\033[0m"


class Tabulator(Generic[_IndexT]):
    """Wrap columns of text.

    Args:
        field_fmts: mapping of field (column) names to a FieldFormat object.
            Use integer keys if your rows data are sequences rather than
            dicts. Integer values will be interpreted as FieldFormat widths.
        total_width: all columns will fit inside this width (e.g., the width
            of your terminal window).
        padding: number of spaces between each column.
        left_margin: number of spaces before the first column.
        right_margin: number of spaces after the last column.
    """

    def __init__(
        self,
        field_fmts: Mapping[_IndexT, FieldFormat | ConvertibleToInt],
        total_width: int = 80,
        padding: int = 2,
        left_margin: int = 1,
        right_margin: int = 1,
    ) -> None:
        self.field_fmts: dict[_IndexT, FieldFormat] = {
            field: self._rectify_format(field_fmts[field]) for field in field_fmts
        }
        self.total_width = total_width
        self.padding = padding
        self.left_margin = left_margin
        self.right_margin = right_margin

    def _wrappers(self) -> dict[_IndexT, textwrap.TextWrapper]:
        """Create TextWrapper objects for fields with known max width.

        _wrappers is *not* ordered like field_fmts is.
        """
        return {
            field: textwrap.TextWrapper(width=fmt.width)
            for field, fmt in self.field_fmts.items()
            if fmt.width != FieldFormat.REMAINING_SPACE
        }

    def tabulate(
        self, rows: Iterable[SupportsGetItem[_IndexT, object]]
    ) -> Generator[str]:
        """Yield one line of table at a time.

        Args:
            rows: an iterable of text rows.
                Each text row can be: a sequence of strings (indexed by
                integer) or a mapping of field (column) names to a string
                (where order is therefore unimportant).

        Yields:
            One str for each line of resulting table.
                If rows is empty, yield nothing.

        Raises:
            LookupError: If a field from `field_fmts` is not found in a row.
        """
        wrappers = self._wrappers()

        # Wrap to max widths
        wrapped_rows: list[dict[_IndexT, str | list[str]]] = []
        for row in rows:
            new_row: dict[_IndexT, str | list[str]] = {}
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
        sizes: dict[_IndexT, int] = {}
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

        # wrapped_rows is now List[Dict[_IndexT, List[str]]]
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
                cells = (
                    cell.ljust(width)
                    for width, cell in zip(sizes.values(), line, strict=True)
                )
                out = line_template.format(
                    left_margin=" " * self.left_margin,
                    cells=(" " * self.padding).join(cells),
                    right_margin=" " * self.right_margin,
                )
                yield out

    @staticmethod
    def _rectify_format(val: FieldFormat | ConvertibleToInt) -> FieldFormat:
        """Pass int-able values into a FieldFormat object."""
        if not isinstance(val, FieldFormat):
            # Do not catch ValueError, TypeError
            return FieldFormat(int(val))
        return val


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
