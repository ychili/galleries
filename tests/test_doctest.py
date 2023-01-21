import doctest
import unittest

from galleries import galleryms, util


def load_tests(unused_loader, tests, unused_ignore):
    tests.addTests(doctest.DocFileSuite("doctest.rst"))
    for module in (galleryms, util):
        tests.addTests(doctest.DocTestSuite(module))
    return tests
