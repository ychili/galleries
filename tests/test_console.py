"""Unit tests for console"""

import unittest

import hypothesis
import hypothesis.strategies as st

import galleries.console


class TestFieldFormat(unittest.TestCase):
    @hypothesis.given(
        st.text().filter(lambda s: s not in galleries.console.FieldFormat.COLORS)
    )
    def test_unknown_arguments(self, key):
        # Unknown color arguments raise KeyError:
        with self.assertRaises(KeyError):
            galleries.console.FieldFormat.from_names(-80, fg=key)
        with self.assertRaises(KeyError):
            galleries.console.FieldFormat.from_names(-80, bg=key)
        # Unknown effect arguments are accepted:
        self.assertIn(
            key, galleries.console.FieldFormat.from_names(-80, effect=key).sgr
        )

    lines_strategy = st.iterables(st.text())

    @hypothesis.given(lines_strategy)
    def test_colorize_no_op(self, lines):
        null = galleries.console.FieldFormat(-80)
        lines_in = list(lines)
        lines_out = list(null.colorize(lines_in))
        self.assertEqual(lines_in, lines_out)

    @hypothesis.given(lines_strategy)
    def test_colorize_normal(self, lines):
        blue = galleries.console.FieldFormat.from_names(-80, "blue")
        lines_in = list(lines)
        for line_in, line_out in zip(lines_in, blue.colorize(lines_in), strict=True):
            expected_out = f"\033[34m{line_in}\033[0m"
            self.assertEqual(line_out, expected_out)


class TestTabulator(unittest.TestCase):
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
        self.assertEqual(len(list(tabulator.tabulate(rows))), 19)

    def test_format_rectification(self):
        tabulator = galleries.console.Tabulator({0: 10})
        self.assertEqual(tabulator.field_fmts, {0: galleries.console.FieldFormat(10)})

    def test_tabulate_empty_input(self):
        tabulator = galleries.console.Tabulator({0: 10})
        self.assertFalse(list(tabulator.tabulate(iter([]))))

    def test_tabulate_empty_values(self):
        tabulator = galleries.console.Tabulator({0: 10})
        rows = iter([[""], [""], ["12345"], [""]])
        self.assertEqual(len(list(tabulator.tabulate(rows))), 4)


if __name__ == "__main__":
    unittest.main()
