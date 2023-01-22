import doctest
import unittest

from galleries import galleryms, relatedtag, util


def load_tests(unused_loader, tests, unused_ignore):
    tests.addTests(doctest.DocFileSuite("doctest.rst"))
    for module in (galleryms, relatedtag, util):
        tests.addTests(doctest.DocTestSuite(module))
    return tests
