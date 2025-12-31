"""Unit tests for galleryms"""

import operator
import string
import unittest

import hypothesis
import hypothesis.strategies

import galleries.galleryms

positive_integers = hypothesis.strategies.integers(min_value=1)


class TestImplicationGraph(unittest.TestCase):
    _make = staticmethod(galleries.galleryms.ImplicationGraph)

    def _assert_cycle(self, graph, cycle):
        ig = self._make(graph)
        err = ig.find_cycle()
        self.assertEqual(cycle, err)

    def test_simple(self):
        self._assert_cycle({1: {2}, 2: {3}}, None)

    def test_empty(self):
        self._assert_cycle({}, None)

    def test_descendants(self):
        ig = self._make({"1": {"2"}, "2": {"3"}})
        top = ig.descendants_of("1")
        self.assertEqual(sorted(top), ["2", "3"])
        middle = ig.descendants_of("2")
        self.assertEqual(sorted(middle), ["3"])
        end = ig.descendants_of("3")
        self.assertEqual(sorted(end), [])
        none = ig.descendants_of("4")
        self.assertEqual(sorted(none), [])

    def test_join_descendants(self):
        ig = self._make({"1": {"2"}, "2": {"3"}, "4": {"5"}})
        test_set = galleries.galleryms.TagSet({"1", "5"})
        ig.join_descendants(test_set, "6")
        self.assertEqual(sorted(test_set), ["1", "5", "6"])
        ig.join_descendants(test_set, "2")
        self.assertEqual(sorted(test_set), ["1", "2", "3", "5", "6"])

    def test_cycle(self):
        # Self cycle
        self._assert_cycle({1: {1}}, [1, 1])
        # Simple cycle
        self._assert_cycle({1: {2}, 2: {1}}, [1, 2, 1])
        # Indirect cycle
        self._assert_cycle({1: {2}, 2: {3}, 3: {1}}, [1, 2, 3, 1])
        # not all elements involved in a cycle
        self._assert_cycle({1: {2}, 2: {3}, 3: {1}, 5: {4}, 4: {6}}, [1, 2, 3, 1])
        # Multiple cycles
        self._assert_cycle({1: {2}, 2: {1}, 3: {4}, 4: {5}, 6: {7}, 7: {6}}, [1, 2, 1])
        # Cycle in the middle of the graph
        self._assert_cycle({1: {2}, 2: {3}, 3: {2, 4}, 4: {5}}, [2, 3, 2])


class TestImplicator(unittest.TestCase):
    def test_aliased_implication(self):
        implicator = galleries.galleryms.Implicator()
        self.assertEqual(implicator.validate_implications_not_aliased(), [])
        implication = galleries.galleryms.RegularImplication("a", "b")
        implicator.add(implication)
        self.assertEqual(implicator.validate_implications_not_aliased(), [])
        implicator.aliases["a"] = "c"
        self.assertEqual(
            implicator.validate_implications_not_aliased(),
            [galleries.galleryms.AliasedImplication(implication, "a", "c")],
        )

    def test_transitive_aliases(self):
        implicator = galleries.galleryms.Implicator()
        self.assertEqual(implicator.validate_aliases_not_aliased(), [])
        implicator.aliases["a"] = "c"
        self.assertEqual(implicator.validate_aliases_not_aliased(), [])
        implicator.aliases["d"] = "a"
        self.assertEqual(implicator.validate_aliases_not_aliased(), [("d", "a", "c")])


class TestGallery(unittest.TestCase):
    def test_merge_tags(self):
        values = ["a b c", "d", galleries.galleryms.TagSet("abc")]
        gallery = galleries.galleryms.Gallery(zip("FGH", values, strict=True))
        tags = gallery.merge_tags(*"FGH")
        self.assertEqual(tags, galleries.galleryms.TagSet("abcd"))

    def test_normalize_tags_args(self):
        gallery = galleries.galleryms.Gallery()
        self.assertRaises(KeyError, gallery.normalize_tags, "Null")
        gallery["Field"] = object()
        self.assertRaises(TypeError, gallery.normalize_tags, "Field")

    def test_get_folder_args(self):
        gallery = galleries.galleryms.Gallery()
        self.assertRaises(KeyError, gallery.get_folder, "Null")
        gallery["Field"] = object()
        self.assertRaises(TypeError, gallery.get_folder, "Field")

    def test_get_folder_default(self):
        gallery = galleries.galleryms.Gallery()
        folder_name = "Gallery01"
        gallery["Field"] = folder_name
        path = gallery.get_folder("Field")
        self.assertEqual(path.parts, (folder_name,))

    def test___repr__(self):
        gallery = galleries.galleryms.Gallery()
        self.assertEqual(repr(gallery), "Gallery()")
        sentinel = object()
        gallery["field"] = sentinel
        self.assertEqual(repr(gallery), f"Gallery({{'field': {sentinel!r}}})")


class TestSearchTerm(unittest.TestCase):
    def test_fields(self):
        # A search term with no fields will never match anything
        term = galleries.galleryms.WildcardSearchTerm("*tok*")
        gallery_1 = galleries.galleryms.Gallery({"tags": "tok1 tak2"})
        self.assertEqual(term.fields, [])
        self.assertEqual(list(term.tagsets(gallery_1)), [])
        term.fields.append("tags")
        self.assertEqual(
            list(term.tagsets(gallery_1)),
            [galleries.galleryms.TagSet({"tok1", "tak2"})],
        )
        # gallery_1 matches
        self.assertTrue(term.match(gallery_1))
        gallery_2 = galleries.galleryms.Gallery({"tags": "tak2"})
        # gallery_2 does not match
        self.assertIs(term.match(gallery_2), None)

    @staticmethod
    def basic_term():
        """Basic search term with one field argument"""
        return galleries.galleryms.WholeSearchTerm("tok1", fields=["Tags"])

    def test_disambiguate_fields_valid(self):
        term = self.basic_term()
        identity = ["Tags"]
        valid_prefix = ["Tags A"]
        for known_fieldnames in (identity, valid_prefix):
            term.disambiguate_fields(known_fieldnames)
            self.assertEqual(term.fields, known_fieldnames)

    def test_disambiguate_fields_invalid(self):
        term = self.basic_term()
        no_candidates = ["General Tags", "Local Tags", "Technical Tags"]
        with self.assertRaises(galleries.galleryms.NoCandidatesError):
            term.disambiguate_fields(no_candidates)

    def test_disambiguate_fields_ambiguous(self):
        term = self.basic_term()
        ambiguous = ["Tags A", "Tags B"]
        with self.assertRaises(galleries.galleryms.MultipleCandidatesError):
            term.disambiguate_fields(ambiguous)

    def test_whole_search_term(self):
        term = self.basic_term()
        matching_gallery = galleries.galleryms.Gallery(Tags="tok1")
        self.assertEqual(term.match(matching_gallery), "tok1")
        gallery_with_empty_tagset = galleries.galleryms.Gallery(Tags="")
        self.assertIsNone(term.match(gallery_with_empty_tagset))

    def test_wildcard_search_term(self):
        term = galleries.galleryms.WildcardSearchTerm("*", fields="tags")
        gallery = galleries.galleryms.Gallery()
        self.assertRaises(KeyError, term.match, gallery)
        tag_set = galleries.galleryms.TagSet()
        gallery["tags"] = tag_set
        self.assertIsNone(term.match(gallery))
        tag_set.add("0")
        match_result = term.match(gallery)
        assert match_result
        self.assertEqual(match_result.group(0), "0")
        term.word = "1"
        self.assertIsNone(term.match(gallery))
        tag_set.add("1")
        self.assertTrue(term.match(gallery))

    def test_numeric_condition(self):
        term = galleries.galleryms.NumericCondition(operator.eq, 15, fields="area")
        normal_gallery = galleries.galleryms.Gallery(area="15.159")
        self.assertFalse(term.match(normal_gallery))
        invalid_gallery = galleries.galleryms.Gallery(area="alphanum")
        self.assertFalse(term.match(invalid_gallery))

    def test_cardinality_condition(self):
        sentinel = object()

        def compare(enclosed, cardinality):
            return sentinel if enclosed == cardinality else None

        term = galleries.galleryms.CardinalityCondition(compare, 4, fields="tags")
        gallery = galleries.galleryms.Gallery(tags="0 1 2 3")
        self.assertIs(term.match(gallery), sentinel)
        term.argument = -1
        self.assertFalse(term.match(gallery))


class TestLogicalSearchGroup(unittest.TestCase):
    def test_all_terms(self):
        term = TestSearchTerm.basic_term()
        query = galleries.galleryms.ConjunctiveSearchGroup([term])
        self.assertEqual(list(query.all_terms()), [term])
        query = galleries.galleryms.ConjunctiveSearchGroup(
            [term, galleries.galleryms.NegativeSearchGroup([term])]
        )
        self.assertEqual(list(query.all_terms()), [term, term])


class TestRelatedTag(unittest.TestCase):
    _TYPICAL_COUNT = galleries.galleryms.TagCount("a", 15)

    def _make(self, tag_count=None, overlap_count=0, search_count=0):
        tag_count = tag_count or self._TYPICAL_COUNT
        return galleries.galleryms.RelatedTag(tag_count, overlap_count, search_count)

    @hypothesis.given(count_a=positive_integers, count_b=positive_integers)
    def test_no_overlap(self, count_a, count_b):
        """Where A and B are disjoint"""
        no_overlap = galleries.galleryms.RelatedTag(
            galleries.galleryms.TagCount("tag", count_a),
            overlap_count=0,
            search_count=count_b,
        )
        method_names = [
            "cosine_similarity",
            "jaccard_index",
            "overlap_coefficient",
            "frequency",
        ]
        # All zero
        for func in map(operator.methodcaller, method_names):
            self.assertEqual(func(no_overlap), 0.0)

    def test_partial_overlap(self):
        """Where A and B intersect"""
        partial = self._make(overlap_count=1, search_count=20)
        self.assertAlmostEqual(partial.cosine_similarity(), 0.05773502691896257)
        self.assertAlmostEqual(partial.jaccard_index(), 0.029411764705882353)
        self.assertAlmostEqual(partial.overlap_coefficient(), 0.06666666666666667)
        self.assertAlmostEqual(partial.frequency(), 0.06666666666666667)

    def test_subset(self):
        """Where A is a subset of B"""
        subset = self._make(overlap_count=15, search_count=20)
        self.assertAlmostEqual(subset.cosine_similarity(), 0.8660254037844386)
        self.assertAlmostEqual(subset.jaccard_index(), 0.75)
        self.assertEqual(subset.overlap_coefficient(), 1.0)
        self.assertEqual(subset.frequency(), 1.0)

    @hypothesis.given(count_a=positive_integers)
    def test_empty(self, count_a):
        """Where B is empty"""
        zero = galleries.galleryms.RelatedTag(
            galleries.galleryms.TagCount("tag", count_a),
            search_count=0,
            overlap_count=0,
        )
        with self.assertRaises(ZeroDivisionError):
            zero.cosine_similarity()
        self.assertEqual(zero.jaccard_index(), 0.0)
        with self.assertRaises(ZeroDivisionError):
            zero.overlap_coefficient()
        self.assertEqual(zero.frequency(), 0.0)


class TestTagSet(unittest.TestCase):
    @hypothesis.given(chars=hypothesis.strategies.text(string.whitespace))
    def test_whitespace(self, chars):
        """
        Constructing a ``TagSet`` from a tagstring containing only whitespace
        characters will produce an empty, falsy ``TagSet``.
        """
        self.assertFalse(galleries.galleryms.TagSet.from_tagstring(chars))

    @hypothesis.given(
        tag_set=hypothesis.strategies.builds(galleries.galleryms.TagSet.from_tagstring)
    )
    def test_roundtrip___str___from_tagstring(self, tag_set):
        """
        Given a ``TagSet`` created from an arbitrary string, its string
        representation will be losslessly convertible back to a ``TagSet``.
        """
        self.assertEqual(
            galleries.galleryms.TagSet.from_tagstring(str(tag_set)), tag_set
        )

    def test_apply_implications(self):
        tags = {"Rome", "New Amsterdam", "Tenochtitlan"}
        tag_set_1 = galleries.galleryms.TagSet(tags)
        tag_set_1.apply_implications([])
        # Applying no implications will leave the tag set unmodified.
        self.assertEqual(tag_set_1, galleries.galleryms.TagSet(tags))

    def test_apply_aliases(self):
        aliases = {"Constantinople": "İstanbul", "New Amsterdam": "New York"}
        tag_set = galleries.galleryms.TagSet({"Rome", "New Amsterdam", "Tenochtitlan"})
        tag_set.apply_aliases(aliases)
        self.assertEqual(tag_set, {"Rome", "New York", "Tenochtitlan"})


class TestSplitOnWhitespace(unittest.TestCase):
    WHITESPACE_CHARACTERS = frozenset("\t\n\x0b\x0c\r\x1c\x1d\x1e\x1f \x85\xa0")
    CHR_MAX = 0x100
    _TEST_STRINGS = [
        ("", []),
        ("a", ["a"]),
        ("a  b", ["a", "b"]),
        (" a b c\t", ["a", "b", "c"]),
        ("def ghi", ["def", "ghi"]),
    ]

    def test_single_unicode_characters(self):
        for i in range(self.CHR_MAX):
            char = chr(i)
            with self.subTest(char=char):
                if galleries.galleryms.split_on_whitespace(char):
                    self.assertNotIn(
                        char,
                        self.WHITESPACE_CHARACTERS,
                        "Non-empty list returned. char not considered whitespace.",
                    )
                else:
                    self.assertIn(
                        char,
                        self.WHITESPACE_CHARACTERS,
                        "Empty list returned. "
                        "Expect char to be in set of known whitespace characters.",
                    )

    @hypothesis.given(hypothesis.strategies.text(WHITESPACE_CHARACTERS))
    def test_whitespace_strings(self, chars):
        self.assertFalse(galleries.galleryms.split_on_whitespace(chars))

    def test_strings(self):
        for test, expected in self._TEST_STRINGS:
            with self.subTest(string=test):
                self.assertEqual(
                    galleries.galleryms.split_on_whitespace(test), expected
                )


class TestArgumentParser(unittest.TestCase):
    def setUp(self):
        self.parser = galleries.galleryms.ArgumentParser()

    INVALID_ARGUMENTS = ["", *"~+=:[]", ":a", "a:", "=a", "a=", "n[]="]
    REQUIRED_CHARS = {
        *string.ascii_letters,
        *string.digits,
        *"_-%",
        *"İı",  # These match [a-z], because Turkish.
    }

    def test_parse_argument_failing_examples(self):
        for argument in self.INVALID_ARGUMENTS:
            with self.subTest(argument=argument):
                with self.assertRaises(galleries.galleryms.ArgumentParsingError):
                    self.parser.parse_argument(argument)

    @hypothesis.given(
        hypothesis.strategies.text(
            hypothesis.strategies.characters(blacklist_characters=REQUIRED_CHARS)
        )
    )
    def test_parse_argument_characters_failing(self, text):
        """
        An argument that does not contain one of these required characters
        will fail to parse.
        """
        self.assertRaises(
            galleries.galleryms.ArgumentParsingError, self.parser.parse_argument, text
        )


class TestDescriptorImplication(unittest.TestCase):
    def test_match(self):
        empty = galleries.galleryms.DescriptorImplication("")
        self.assertIsNone(empty.match("_"))
        self.assertEqual(empty.match("_a"), "a")
        blue = galleries.galleryms.DescriptorImplication("blue")
        self.assertIsNone(blue.match("blue_"))
        self.assertEqual(blue.match("blue_color"), "color")
        self.assertIsNone(blue.match("light_blue_color"))


class TestFieldFormat(unittest.TestCase):
    @hypothesis.given(
        hypothesis.strategies.text().filter(
            lambda s: s not in galleries.galleryms.FieldFormat.COLORS
        )
    )
    def test_unknown_arguments(self, key):
        # Unknown color arguments raise KeyError:
        with self.assertRaises(KeyError):
            galleries.galleryms.FieldFormat.from_names(-80, fg=key)
        with self.assertRaises(KeyError):
            galleries.galleryms.FieldFormat.from_names(-80, bg=key)
        # Unknown effect arguments are accepted:
        self.assertIn(
            key, galleries.galleryms.FieldFormat.from_names(-80, effect=key).sgr
        )

    lines_strategy = hypothesis.strategies.iterables(hypothesis.strategies.text())

    @hypothesis.given(lines_strategy)
    def test_colorize_no_op(self, lines):
        null = galleries.galleryms.FieldFormat(-80)
        lines_in = list(lines)
        lines_out = list(null.colorize(lines_in))
        self.assertEqual(lines_in, lines_out)

    @hypothesis.given(lines_strategy)
    def test_colorize_normal(self, lines):
        blue = galleries.galleryms.FieldFormat.from_names(-80, "blue")
        lines_in = list(lines)
        for line_in, line_out in zip(lines_in, blue.colorize(lines_in), strict=True):
            expected_out = f"\033[34m{line_in}\033[0m"
            self.assertEqual(line_out, expected_out)


class TestTabulator(unittest.TestCase):
    def test_integer_indices(self):
        ff = {0: galleries.galleryms.FieldFormat(10)}
        tabulator = galleries.galleryms.Tabulator(ff)
        rows = iter(
            [
                ["Lorem ipsum dolor sit amet, consectetur adipiscing elit"],
                ["Ut enim ad minim veniam, quis nostrud exercitation"],
                ["Excepteur sint occaecat cupidatat non proident"],
            ]
        )
        self.assertEqual(len(list(tabulator.tabulate(rows))), 19)


class TestMostCommon(unittest.TestCase):
    _ITERABLE = [1, 2, 3, 1, 2, 1]
    _EXPECTED = [3, 2, 2, 1, 1, 1]

    def _func(self, n=None, key=lambda item: item):
        return galleries.galleryms.most_common(self._ITERABLE, key=key, n=n)

    def test_values_of_n(self):
        for value in (None, 0):
            # None and 0 are equivalent arguments.
            self.assertEqual(self._func(n=value), self._EXPECTED)
        for i in range(1, 7):
            self.assertEqual(self._func(n=i), self._EXPECTED[:i])
        for i in range(-7, -1):
            self.assertEqual(self._func(n=i), self._EXPECTED[:i])

    def test_keys(self):
        self.assertEqual(self._func(key=float), self._EXPECTED)
        self.assertEqual(
            galleries.galleryms.most_common("abcaba", key=lambda c: -ord(c)),
            list("aaabbc"),
        )


if __name__ == "__main__":
    unittest.main()
