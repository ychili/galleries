"""Unit tests for galleryms"""

import itertools
import operator
import string
import unittest

import galleries.galleryms


class TestImplicationGraph(unittest.TestCase):
    @staticmethod
    def _make(graph):
        return galleries.galleryms.ImplicationGraph(graph)

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
        self.assertEqual(
            implicator.validate_aliases_not_aliased(),
            [("d", "a", "c")],
        )


class TestGallery(unittest.TestCase):
    def test_merge_tags(self):
        values = ["a b c", "d", galleries.galleryms.TagSet("abc")]
        gallery = galleries.galleryms.Gallery(
            {field: val for field, val in zip("FGH", values)}
        )
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

    def test_numeric_condition(self):
        term = galleries.galleryms.NumericCondition(operator.eq, 15, fields="area")
        normal_gallery = galleries.galleryms.Gallery(area="15.159")
        self.assertFalse(term.match(normal_gallery))
        invalid_gallery = galleries.galleryms.Gallery(area="alphanum")
        self.assertFalse(term.match(invalid_gallery))


class TestQuery(unittest.TestCase):
    def test_truthiness(self):
        query = galleries.galleryms.Query()
        self.assertFalse(query)
        query = galleries.galleryms.Query([TestSearchTerm.basic_term()])
        self.assertTrue(query)

    def test_all_terms(self):
        term = TestSearchTerm.basic_term()
        query = galleries.galleryms.Query(conjuncts=[term])
        self.assertEqual(list(query.all_terms()), [term])
        query = galleries.galleryms.Query(conjuncts=[term], negations=[term])
        self.assertEqual(list(query.all_terms()), [term, term])


class TestSimilarityCalculator(unittest.TestCase):
    TYPICAL_COUNTS = (
        galleries.galleryms.TagCount("a", 15),
        galleries.galleryms.TagCount("b", 20),
    )
    B_IS_ZERO = (
        galleries.galleryms.TagCount("a", 4),
        galleries.galleryms.TagCount("b", 0),
    )

    @staticmethod
    def _make(tag_count_a, tag_count_b, overlap):
        return galleries.galleryms.SimilarityCalculator(
            tag_count_a, tag_count_b, overlap
        )

    def test_no_overlap(self):
        """Where A and B are disjoint"""
        no_overlap = self._make(*self.TYPICAL_COUNTS, overlap=0)
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
        partial = self._make(*self.TYPICAL_COUNTS, overlap=1)
        self.assertAlmostEqual(partial.cosine_similarity(), 0.05773502691896257)
        self.assertAlmostEqual(partial.jaccard_index(), 0.029411764705882353)
        self.assertAlmostEqual(partial.overlap_coefficient(), 0.06666666666666667)
        self.assertAlmostEqual(partial.frequency(), 0.06666666666666667)

    def test_subset(self):
        """Where A is a subset of B"""
        subset = self._make(*self.TYPICAL_COUNTS, overlap=15)
        self.assertAlmostEqual(subset.cosine_similarity(), 0.8660254037844386)
        self.assertAlmostEqual(subset.jaccard_index(), 0.75)
        self.assertEqual(subset.overlap_coefficient(), 1.0)
        self.assertEqual(subset.frequency(), 1.0)

    def test_empty(self):
        """Where B is empty"""
        zero = self._make(*self.B_IS_ZERO, overlap=0)
        with self.assertRaises(ZeroDivisionError):
            zero.cosine_similarity()
        self.assertEqual(zero.jaccard_index(), 0.0)
        with self.assertRaises(ZeroDivisionError):
            zero.overlap_coefficient()
        self.assertEqual(zero.frequency(), 0.0)


class TestOverlapTable(unittest.TestCase):
    @staticmethod
    def _make_nontrivial():
        return galleries.galleryms.OverlapTable({"a"}, {"b", "c"}, {"b", "d"})

    def test_require_hashable(self):
        self.assertRaises(TypeError, galleries.galleryms.OverlapTable, [{}])

    def test_containership(self):
        table = galleries.galleryms.OverlapTable()
        self.assertTrue("a" not in table)
        table = self._make_nontrivial()
        self.assertTrue("a" in table)

    def test_iteration(self):
        table = galleries.galleryms.OverlapTable()
        self.assertEqual(list(table), [])
        table = galleries.galleryms.OverlapTable({"a"})
        self.assertEqual(list(table), ["a"])
        table.update({"a", "b"})
        self.assertEqual(list(table), ["a", "b"])

    def test_length(self):
        table = galleries.galleryms.OverlapTable()
        self.assertEqual(len(table), 0)
        table.update(set(string.ascii_lowercase))
        self.assertEqual(len(table), 26)

    def test_frequent_overlaps(self):
        table = self._make_nontrivial()
        sorted_overlaps = table.frequent_overlaps()
        frequent_overlaps = table.frequent_overlaps(n=2)
        self.assertEqual(len(sorted_overlaps), 6)
        self.assertEqual(sorted_overlaps[:2], frequent_overlaps)

    def test_similarities(self):
        table = self._make_nontrivial()
        expected_overlap_results = {"a": 1, "b": 3, "c": 2, "d": 2}
        for tag in "abcd":
            with self.subTest(tag=tag):
                results = list(table.similarities(tag))
                # Results are considered unsorted.
                self.assertEqual(len(results), expected_overlap_results[tag])
                for result in results:
                    self.assertEqual(result.tag_a.tag, tag)
                    self.assertEqual(result.tag_a.count, table.count(tag))


class TestTagSet(unittest.TestCase):
    def test_whitespace(self):
        for char in string.whitespace:
            with self.subTest(char=char):
                # Constructing a TagSet from a tagstring containing a single
                # whitespace character will produce an empty, falsy TagSet.
                self.assertFalse(galleries.galleryms.TagSet.from_tagstring(char))

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

    def test_whitespace_strings_len_2(self):
        for pair in itertools.combinations_with_replacement(string.whitespace, 2):
            short_string = "".join(pair)
            with self.subTest(string=short_string):
                self.assertFalse(galleries.galleryms.split_on_whitespace(short_string))

    def test_whitespace_string_very_long(self):
        for char in self.WHITESPACE_CHARACTERS:
            long_string = char * 1000
            with self.subTest(string=long_string):
                self.assertFalse(galleries.galleryms.split_on_whitespace(long_string))

    def test_strings(self):
        for test, expected in self._TEST_STRINGS:
            with self.subTest(string=test):
                self.assertEqual(
                    galleries.galleryms.split_on_whitespace(test), expected
                )


if __name__ == "__main__":
    unittest.main()
