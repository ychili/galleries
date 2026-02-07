"""Unit tests for util"""

import csv
import io
import sys
import unittest
import unittest.mock

import hypothesis
import hypothesis.strategies

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


class TestReadDB(unittest.TestCase):
    CSV_LINES = ["F,G,H\r\n", "f,g,h\r\n"]
    _EXPECTED_OUT = [galleries.galleryms.Gallery({"F": "f", "G": "g", "H": "h"})]

    def test_file_stdin(self):
        csv_text = "".join(self.CSV_LINES)
        patch_stdin = unittest.mock.patch.object(sys, "stdin", io.StringIO(csv_text))
        with patch_stdin, galleries.util.read_db() as reader:
            glist = list(reader)
        self.assertEqual(glist, self._EXPECTED_OUT)

    def test_file_iterable_lines(self):
        iterable_lines = iter(self.CSV_LINES)
        with galleries.util.read_db(iterable_lines) as reader:
            glist = list(reader)
        self.assertEqual(glist, self._EXPECTED_OUT)

    # Python >3.10 will accept a nul in CSV without error.
    # <https://github.com/python/cpython/pull/28808>
    @hypothesis.example(["\x00"])
    @hypothesis.example(['"'])
    @hypothesis.given(hypothesis.strategies.iterables(hypothesis.strategies.text()))
    def test_roundtrip_read_db_write_galleries(self, csv_lines):
        # Fuzz read_db to find valid CSV.
        try:
            with galleries.util.read_db(csv_lines) as reader_0:
                try:
                    glist = list(reader_0)
                except galleries.util.FieldMismatchError:
                    hypothesis.reject()
        except csv.Error:
            hypothesis.reject()
        # Then, write and read the data again to test round-trip consistency.
        buf = io.StringIO()
        galleries.util.write_galleries(glist, reader_0.fieldnames, buf)
        buf.seek(0)
        with galleries.util.read_db(buf) as reader_1:
            self.assertEqual(glist, list(reader_1))


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
