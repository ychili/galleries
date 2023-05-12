import doctest
import unittest

from galleries import galleryms, refresh, relatedtag, util


def load_tests(unused_loader, tests, unused_ignore):
    tests.addTests(doctest.DocFileSuite("doctest.rst"))
    for module in (galleryms, refresh, relatedtag, util):
        tests.addTests(doctest.DocTestSuite(module))
    return tests


if __name__ == "__main__":
    unittest.main()
