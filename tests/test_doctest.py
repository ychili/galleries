"""Gather doctest'ed modules, and test them under unittest."""

import doctest
import unittest

from galleries import galleryms, refresh, util


def load_tests(unused_loader, tests, unused_ignore):
    tests.addTests(doctest.DocFileSuite("doctest.rst"))
    for module in (galleryms, refresh, util):
        tests.addTests(doctest.DocTestSuite(module))
    return tests


if __name__ == "__main__":
    unittest.main()
