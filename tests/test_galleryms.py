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


class TestSearchTerm(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
