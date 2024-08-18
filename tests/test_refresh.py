"""Unit tests for refresh"""

import itertools
import unittest

import galleries.galleryms
import galleries.refresh

SETS = {
    "colors": ["red", "green", "blue"],
    "things": ["car", "truck", "airplane"],
}


class TestTagActionsObject(unittest.TestCase):
    simple = {
        "fieldnames": ["Tags"],
        "Tags": {"implications": {"blue_dog": "dog"}, "aliases": {"doggy": "dog"}},
    }
    descriptors = {
        "fieldnames": ["Tags"],
        "Tags": {
            "descriptors": {
                "sets": SETS,
                "chains": {"colored_things": ["colors", "things"]},
            }
        },
    }
    multi_implications = {
        "multi-implications": {
            "ignored": [],
            "single": ["consequent"],
            "double": ["1st", "2nd"],
        }
    }
    fieldgroups = {
        "fieldgroups": {"TagFields": ["Category A", "Category B"]},
        "TagFields": {"implications": {"ape": "mammal"}},
    }
    missing_table = {"fieldnames": ["Tags"], "Tagz": {}}
    wrong_type = {"implications": [], "aliases": "Not a mapping"}
    empty_fieldgroup = {"fieldgroups": {"TagFields": []}, "TagFields": {}}
    overwriting_set = {
        "descriptors": {"sets": SETS, "unions": {"things": ["colors", "things"]}}
    }
    bad_reference = {
        "descriptors": {"sets": SETS, "unions": {"misspelled": ["colours", "things"]}}
    }
    invalid_chains = {
        "descriptors": {
            "sets": SETS,
            "chains": {"empty": [], "bad_reference": ["colours", "spam"]},
        }
    }
    multiple_updates = [
        {"implications": {"red_stapler": "stapler"}},
        {"implications": {"striped_cat": "cat"}, "aliases": {"kitty": "cat"}},
    ]

    def setUp(self):
        self.tao = galleries.refresh.TagActionsObject()

    def test_default_fields(self):
        self.assertEqual(self.tao.default_tag_fields, frozenset())

    def test_no_implicators(self):
        self.assertFalse(list(self.tao.implicators()))

    def _assert_implicators_equal(self, impl1, impl2):
        self.assertEqual(impl1.implications, impl2.implications)
        self.assertEqual(impl1.aliases, impl2.aliases)

    def test_simple(self):
        self.tao.update(self.simple)
        implic = self.tao.get_implicator("Tags")
        self.assertEqual(
            implic.implications,
            {galleries.galleryms.RegularImplication("blue_dog", "dog")},
        )
        self.assertEqual(implic.aliases, {"doggy": "dog"})
        implicators = list(self.tao.implicators())
        self.assertEqual(len(implicators), 1)
        self.assertEqual(implicators[0][0], {"Tags"})
        # The two methods of getting Implicators, get_implicator and
        # implicators, should produce identical results.
        self._assert_implicators_equal(implicators[0][1], implic)

    def test_descriptors(self):
        self.tao.update(self.descriptors)
        impl = self.tao.get_implicator("Tags").implications
        # impl == {RegularImplication('red_truck', 'truck'), ... }
        self.assertEqual(len(impl), 9)
        implicators = list(self.tao.implicators())
        self.assertEqual(len(implicators), 1)
        self.assertEqual(implicators[0][0], {"Tags"})
        self.assertEqual(impl, implicators[0][1].implications)

    def test_multi_implications(self):
        self.tao.update(self.multi_implications)
        implic = self.tao.get_implicator()
        self.assertEqual(len(implic.implications), 3)
        self.assertEqual(implic.tags_implied_by("double"), {"1st", "2nd"})
        implicators = list(self.tao.implicators())
        self.assertFalse(implicators)

    def test_fieldgroups(self):
        self.tao.update(self.fieldgroups)
        implic_a = self.tao.get_implicator("Category A")
        self.assertEqual(
            implic_a.implications,
            {galleries.galleryms.RegularImplication("ape", "mammal")},
        )
        self.assertEqual(implic_a.aliases, {})
        implicators = list(self.tao.implicators())
        self.assertEqual(len(implicators), 1)
        self.assertEqual(implicators[0][0], {"Category A", "Category B"})
        implic_b = self.tao.get_implicator("Category B")
        for impl1, impl2 in itertools.combinations(
            [implic_a, implic_b, implicators[0][1]], 2
        ):
            self._assert_implicators_equal(impl1, impl2)

    def test_missing_table(self):
        with self.assertLogs() as cm:
            self.tao.update(self.missing_table)
        self._assert_log(cm, "In <???>: At Tags: Table not found with name: Tags")

    def test_wrong_type(self):
        with self.assertLogs() as cm:
            self.tao.update(self.wrong_type)
        self._assert_log(
            cm,
            "In <???>: At aliases: Expected a mapping, got a <class 'str'>",
            "In <???>: At implications: Expected a mapping, got a <class 'list'>",
        )

    def test_empty_fieldgroup(self):
        with self.assertLogs() as cm:
            self.tao.update(self.empty_fieldgroup)
        self._assert_log(
            cm, "In <???>: At fieldgroups.TagFields: Can't use an empty fieldgroup"
        )

    def test_overwriting_set(self):
        with self.assertLogs() as cm:
            self.tao.update(self.overwriting_set)
        self._assert_log(
            cm,
            "In <???>: At descriptors.unions.things: Over-writing set name with union: things",
        )

    def test_bad_reference(self):
        with self.assertLogs() as cm:
            self.tao.update(self.bad_reference)
        self._assert_log(
            cm,
            "In <???>: At descriptors.unions.misspelled: Bad set/union name: 'colours'",
        )

    def test_invalid_chains(self):
        with self.assertLogs() as cm:
            self.tao.update(self.invalid_chains)
        self._assert_log(
            cm,
            "In <???>: At descriptors.chains.empty: Chain has fewer than two names in it: empty",
            "In <???>: At descriptors.chains.bad_reference: Bad set/union name: 'spam'",
        )

    def test_multiple_updates_no_default(self):
        for obj in self.multiple_updates:
            self.tao.update(obj)
        implic = self.tao.get_implicator()
        self.assertEqual(implic.aliases.get("kitty"), "cat")
        self.assertEqual(implic.tags_implied_by("red_stapler"), {"stapler"})
        self.assertEqual(implic.tags_implied_by("striped_cat"), {"cat"})
        implicators = list(self.tao.implicators())
        self.assertFalse(implicators)

    def test_multiple_updates_with_default(self):
        fieldname = "TAGS"
        self.tao.default_tag_fields = frozenset([fieldname, *"ABC"])
        for obj in self.multiple_updates:
            self.tao.update(obj)
        implic = self.tao.get_implicator(fieldname)
        self.assertEqual(implic.aliases.get("kitty"), "cat")
        self.assertEqual(implic.tags_implied_by("red_stapler"), {"stapler"})
        self.assertEqual(implic.tags_implied_by("striped_cat"), {"cat"})
        implicators = list(self.tao.implicators())
        self.assertEqual(len(implicators), 1)
        self.assertEqual(implicators[0][0], {fieldname, *"ABC"})
        self._assert_implicators_equal(implic, implicators[0][1])

    def test_get_with_unknown_fieldname(self):
        implic = self.tao.get_implicator("X")
        self.assertFalse(implic.implications)
        self.assertFalse(implic.aliases)

    def _assert_log(self, context_manager, *strings):
        for s in strings:
            self.assertTrue(any(s in msg for msg in context_manager.output))


if __name__ == "__main__":
    unittest.main()
