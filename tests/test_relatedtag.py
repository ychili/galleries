"""Unit tests for relatedtag, using pytest"""

import sys

import pytest

import galleries.galleryms
import galleries.relatedtag

SETS = (
    galleries.galleryms.TagSet(s)
    for s in [set("abc"), set("cde"), set("efg"), set("xyz")]
)


@pytest.mark.parametrize(
    ("sets_in", "expected_len", "expected_n_sets"), [(SETS, 10, 4), ([], 0, 0)]
)
def test_overlap_table(sets_in, expected_len, expected_n_sets):
    table = galleries.relatedtag.overlap_table(sets_in)
    assert len(table) == expected_len
    assert table.n_sets == expected_n_sets


def test_results_table():
    printer = galleries.relatedtag.results_table(sys.stdout)
    assert printer.file == sys.stdout
    assert all(
        body_field in printer.header for body_field in printer.tabulator.field_fmts
    )
    assert all(
        header_field in printer.tabulator.field_fmts for header_field in printer.header
    )
    assert all(
        -7 <= field_fmt.width <= 7
        for field_fmt in printer.tabulator.field_fmts.values()
    )
    assert all(
        number_format in printer.tabulator.field_fmts
        for number_format in printer.formats
    )
