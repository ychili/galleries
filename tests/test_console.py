"""Unit tests for console, using pytest"""

import hypothesis
import hypothesis.strategies as st
import pytest

import galleries.console


class ConsoleTestCase:
    pass


class TestFieldFormat(ConsoleTestCase):
    @hypothesis.given(
        st.text().filter(
            lambda s: s not in galleries.console.FieldFormat.COLORS
            and s not in galleries.console.FieldFormat.EFFECTS
        )
    )
    def test_unknown_arguments(self, key):
        # Unknown color arguments raise KeyError:
        with pytest.raises(KeyError):
            galleries.console.FieldFormat.from_names(-80, fg=key)
        with pytest.raises(KeyError):
            galleries.console.FieldFormat.from_names(-80, bg=key)
        # Unknown effect arguments are accepted:
        assert key in galleries.console.FieldFormat.from_names(-80, effect=key).sgr

    lines_strategy = st.iterables(st.text())

    @hypothesis.given(lines_strategy)
    def test_colorize_no_op(self, lines):
        null = galleries.console.FieldFormat(-80)
        lines_in = list(lines)
        lines_out = list(null.colorize(lines_in))
        assert lines_in == lines_out

    @hypothesis.given(lines_strategy)
    def test_colorize_normal(self, lines):
        blue = galleries.console.FieldFormat.from_names(-80, "blue")
        lines_in = list(lines)
        for line_in, line_out in zip(lines_in, blue.colorize(lines_in), strict=True):
            expected_out = f"\033[34m{line_in}\033[0m"
            assert line_out == expected_out


class TestTabulator(ConsoleTestCase):
    def test_integer_indices(self):
        ff = {0: galleries.console.FieldFormat(10)}
        tabulator = galleries.console.Tabulator(ff)
        rows = iter(
            [
                ["Lorem ipsum dolor sit amet, consectetur adipiscing elit"],
                ["Ut enim ad minim veniam, quis nostrud exercitation"],
                ["Excepteur sint occaecat cupidatat non proident"],
            ]
        )
        assert len(list(tabulator.tabulate(rows))) == 19

    def test_format_rectification(self):
        tabulator = galleries.console.Tabulator({0: 10})
        assert tabulator.field_fmts == {0: galleries.console.FieldFormat(10)}

    def test_tabulate_empty_input(self):
        tabulator = galleries.console.Tabulator({0: 10})
        assert not list(tabulator.tabulate(iter([])))

    def test_tabulate_empty_values(self):
        tabulator = galleries.console.Tabulator({0: 10})
        rows = iter([[""], [""], ["12345"], [""]])
        assert len(list(tabulator.tabulate(rows))) == 4


class TestDistribute(ConsoleTestCase):
    COLUMN_MAX = 0x4000

    @hypothesis.given(n=st.integers(), k=st.integers(min_value=1, max_value=COLUMN_MAX))
    def test_invariants(self, n, k):
        result = list(galleries.console.distribute(n, k))
        assert sum(result) == n
        assert len(result) == k
