"""Unit tests for util"""

import unittest

import galleries.galleryms
import galleries.util


class TestReader(unittest.TestCase):
    _FIELDNAMES_IN = "F,G,H"
    _FIELDNAMES_OUT = ["F", "G", "H"]

    def test_valid_csv(self):
        reader = galleries.util.StrictReader([self._FIELDNAMES_IN, "f,g,h"])
        self.assertEqual(
            list(galleries.util.Reader(reader)),
            [galleries.galleryms.Gallery({"F": "f", "G": "g", "H": "h"})],
        )

    def test_missing_fields(self):
        reader = galleries.util.StrictReader([self._FIELDNAMES_IN, 'f,"g,"'])
        with self.assertRaises(galleries.util.MissingFieldError) as assert_raises_ctx:
            list(galleries.util.Reader(reader))
        exc = assert_raises_ctx.exception
        self.assertEqual(exc.row, ["f", "g,"])
        self.assertEqual(exc.fieldnames, self._FIELDNAMES_OUT)
        self.assertEqual(exc.line_num, 2)

    def test_extra_fields(self):
        reader = galleries.util.StrictReader([self._FIELDNAMES_IN, "f,g,h,"])
        with self.assertRaises(galleries.util.ExtraFieldError) as assert_raises_ctx:
            list(galleries.util.Reader(reader))
        exc = assert_raises_ctx.exception
        self.assertEqual(exc.row, ["f", "g", "h", ""])
        self.assertEqual(exc.fieldnames, self._FIELDNAMES_OUT)
        self.assertEqual(exc.line_num, 2)


class TestSorting(unittest.TestCase):
    GALLERIES_PATH_DATA = [
        "",
        "folder",
        "Folder/1",
        "Folder/2",
        "Folder/10",
        "Folder/20",
        "Folder (2)",
        "Folder (12)",
    ]
    GALLERIES_PATH_RESULTS = [
        "",
        "folder",
        "Folder (2)",
        "Folder (12)",
        "Folder/1",
        "Folder/2",
        "Folder/10",
        "Folder/20",
    ]

    def _galleries_to_sort(self, fieldname):
        return [
            galleries.galleryms.Gallery({fieldname: data})
            for data in self.GALLERIES_PATH_DATA
        ]

    def test_sort_by_field(self):
        fieldname = "Path"
        it = iter(self._galleries_to_sort(fieldname))
        results = galleries.util.sort_by_field(it, fieldname)
        self.assertEqual([g[fieldname] for g in results], self.GALLERIES_PATH_RESULTS)
        repeat = galleries.util.sort_by_field(results, fieldname)
        self.assertEqual(results, repeat, (results, repeat))

    def test_alphanum_getter_correct_sort(self):
        fieldname = "Path"
        galls = self._galleries_to_sort(fieldname)
        galls.sort(key=galleries.util.alphanum_getter(fieldname))
        self.assertEqual([g[fieldname] for g in galls], self.GALLERIES_PATH_RESULTS)

    def test_alphanum_getter_bad_field(self):
        missing_fieldname = "Other Field"
        empty_gall = [galleries.galleryms.Gallery()]
        normal_galls = self._galleries_to_sort("Path")
        for test in (empty_gall, normal_galls):
            with self.assertRaises(KeyError):
                test.sort(key=galleries.util.alphanum_getter(missing_fieldname))
