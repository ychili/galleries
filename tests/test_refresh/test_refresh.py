"""Unit tests for refresh"""

import itertools
import logging
import unittest

import galleries.galleryms
import galleries.refresh
import galleries.util

SETS = {
    "colors": ["red", "green", "blue"],
    "things": ["car", "truck", "airplane"],
}


class RefreshTestCase(unittest.TestCase):
    def _assert_log(self, context_manager, *strings):
        for s in strings:
            self.assertTrue(any(s in msg for msg in context_manager.output))


class TestGardener(RefreshTestCase):
    _data = [
        {"Field1": "_extra expected", "Field2": "no"},
        {"Field1": "", "Field2": "no"},
    ]
    _mask = galleries.galleryms.TagSet(["_extra"])
    _aliases = {"no": "yes"}

    def setUp(self):
        # Use generator rather than list to ensure we aren't relying on
        # Sequence features.
        self.galleries = (
            galleries.galleryms.Gallery(mapping) for mapping in self._data
        )
        self.gard = galleries.refresh.Gardener()

    def test_null_case(self):
        result = list(self.gard.garden_rows(self.galleries))
        repeat = list(self.gard.garden_rows(result))
        self.assertEqual(result, repeat)

    def test_remove_tags(self):
        fieldname = "Field1"
        self.gard.set_remove_tags(self._mask, fieldname)
        self.assertIn(fieldname, self.gard.needed_fields)
        all_tags_seen = galleries.galleryms.TagSet()
        for gallery in self.gard.garden_rows(self.galleries):
            tag_set = gallery[fieldname]
            assert isinstance(tag_set, galleries.galleryms.TagSet)
            self.assertNotIn("_extra", tag_set)
            all_tags_seen.update(tag_set)
        self.assertIn("expected", all_tags_seen)

    def test_alias_tags(self):
        fieldname = "Field2"
        self.gard.set_alias_tags(self._aliases, fieldname)
        self.assertIn(fieldname, self.gard.needed_fields)
        all_tags_seen = galleries.galleryms.TagSet()
        for gallery in self.gard.garden_rows(self.galleries):
            tag_set = gallery[fieldname]
            assert isinstance(tag_set, galleries.galleryms.TagSet)
            self.assertNotIn("no", tag_set)
            all_tags_seen.update(tag_set)
        self.assertIn("yes", all_tags_seen)

    def test_field_checking(self):
        # "Expected Field" from configuration
        fieldname = "Expected Field"
        self.gard.set_normalize_tags(fieldname)
        self.assertIn(fieldname, self.gard.needed_fields)
        with self.assertRaises(galleries.util.FieldNotFoundError) as assert_raises_ctx:
            # "Bogus Field" is the actual field parsed from the input headers.
            list(self.gard.garden_rows(self.galleries, {"Bogus Field"}))
        self.assertIn(fieldname, assert_raises_ctx.exception.args)

    def test_implicator(self):
        fieldname = "Field1"
        implicator = galleries.galleryms.Implicator(
            implications=[
                galleries.galleryms.RegularImplication("expected", "implied"),
                galleries.galleryms.RegularImplication("off_your_chump", "insane"),
            ],
            aliases=self._aliases,
        )
        self.gard.set_implicator(implicator, fieldname)
        self.assertIn(fieldname, self.gard.needed_fields)
        self.assertNotIn("Field2", self.gard.needed_fields)
        for gallery in self.gard.garden_rows(self.galleries):
            tag_set = gallery[fieldname]
            assert isinstance(tag_set, galleries.galleryms.TagSet)
            if "expected" in tag_set:
                self.assertIn("implied", tag_set)
            self.assertIsInstance(
                gallery["Field2"], str, "Field2 not converted to TagSet"
            )

    def test_unique(self):
        self.gard.set_unique("Field1", "Field2")
        galleries_data = list(self.galleries)
        # One row can't have duplicates:
        galleries_in = galleries_data[:1]
        self.assertEqual(list(self.gard.garden_rows(galleries_in)), galleries_in)
        # Reset data seen:
        self.gard.set_unique("Field1", "Field2")
        with self.assertRaises(
            galleries.refresh.DuplicateValueError
        ) as assert_raises_ctx:
            list(self.gard.garden_rows(galleries_data))
        self.assertEqual(assert_raises_ctx.exception.field, "Field2")
        self.assertEqual(assert_raises_ctx.exception.value, "no")


class TestTagActionsObject(RefreshTestCase):
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
        self.assertEqual(implicators[0][1], implic)

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
        self.assertEqual(implic.graph.tags_implied_by("double"), {"1st", "2nd"})
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
            self.assertEqual(impl1, impl2)

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
        self.assertEqual(implic.graph.tags_implied_by("red_stapler"), {"stapler"})
        self.assertEqual(implic.graph.tags_implied_by("striped_cat"), {"cat"})
        implicators = list(self.tao.implicators())
        self.assertFalse(implicators)

    def test_multiple_updates_with_default(self):
        fieldname = "TAGS"
        self.tao.default_tag_fields = frozenset([fieldname, *"ABC"])
        for obj in self.multiple_updates:
            self.tao.update(obj)
        implic = self.tao.get_implicator(fieldname)
        self.assertEqual(implic.aliases.get("kitty"), "cat")
        self.assertEqual(implic.graph.tags_implied_by("red_stapler"), {"stapler"})
        self.assertEqual(implic.graph.tags_implied_by("striped_cat"), {"cat"})
        implicators = list(self.tao.implicators())
        self.assertEqual(len(implicators), 1)
        self.assertEqual(implicators[0][0], {fieldname, *"ABC"})
        self.assertEqual(implic, implicators[0][1])

    def test_get_with_unknown_fieldname(self):
        implic = self.tao.get_implicator("X")
        self.assertFalse(implic.implications)
        self.assertFalse(implic.aliases)


class TestValidateTagActions(RefreshTestCase):
    @staticmethod
    def validate(*args, **kwds):
        implicator = galleries.galleryms.Implicator(*args, **kwds)
        return galleries.refresh.validate_tag_actions(implicator)

    def test_empty(self):
        errors = self.validate()
        self.assertFalse(errors)

    def test_valid(self):
        implications = [
            galleries.galleryms.RegularImplication(a, b)
            for a, b in ("ab", "cd", "ef", "gh", "ia")
        ]
        aliases = {"y": "z"}
        errors = self.validate(implications, aliases)
        self.assertFalse(errors)

    def test_one_cycle(self):
        implications = [
            galleries.galleryms.RegularImplication(a, b) for a, b in ("ab", "bc", "ca")
        ]
        with self.assertLogs(level=logging.ERROR) as cm:
            errors = self.validate(implications)
        self.assertEqual(errors, 1)
        self._assert_log(cm, "a -> b -> c -> a")

    def test_multiple_cycles(self):
        implications = [
            galleries.galleryms.RegularImplication(a, b)
            for a, b in ("ab", "ba", "de", "ed")
        ]
        with self.assertLogs(level=logging.ERROR):
            errors = self.validate(implications)
        # find_cycle returns after the first cycle found.
        self.assertEqual(errors, 1)

    def test_transitive_alias_errors(self):
        transitive_aliases = {"a": "c", "d": "a"}
        with self.subTest("single"):
            with self.assertLogs(level=logging.ERROR) as cm:
                errors = self.validate(aliases=transitive_aliases)
            self.assertEqual(errors, 1)
            self._assert_log(cm, "d -> a -> c")
        transitive_aliases.update({"x": "y", "y": "z"})
        with self.subTest("multiple"):
            with self.assertLogs(level=logging.ERROR) as cm:
                errors = self.validate(aliases=transitive_aliases)
            self.assertEqual(errors, 2)

    def test_aliased_implication_errors(self):
        implications = [galleries.galleryms.RegularImplication("a", "b")]
        # Test aliasing both antecedent and consequent.
        for msg, aliases in [("antecedent", {"a": "c"}), ("consequent", {"b": "c"})]:
            with self.subTest(msg):
                with self.assertLogs(level=logging.ERROR) as cm:
                    errors = self.validate(implications, aliases)
                self.assertEqual(errors, 1)
                self._assert_log(cm, "'a'", "'b'", "'c'")

    def test_multiple_errors(self):
        implications = [
            galleries.galleryms.RegularImplication(a, b) for a, b in ("ab", "bc", "ca")
        ]
        aliases = {"a": "c", "x": "y", "y": "z"}
        # Expect: 1 cycle, 2 AIs, 1 TA
        # 2 AIs because validate_implications_not_aliased returns:
        # AliasedImplication(implication=RegularImplication('c', 'a'),
        #     antecedent='a', consequent='c')
        # and
        # AliasedImplication(implication=RegularImplication('a', 'b'),
        #     antecedent='a', consequent='c')
        with self.assertLogs(level=logging.ERROR) as cm:
            errors = self.validate(implications, aliases)
        self.assertEqual(errors, 4)
        # validate_tag_actions only reports the first AI.
        self._assert_log(cm, "a -> b -> c -> a", "x -> y -> z", "'a'", "'c'")


if __name__ == "__main__":
    unittest.main()
