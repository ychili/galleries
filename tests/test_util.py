import unittest

import galleries.galleryms
import galleries.util


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
