"""Unit tests for relatedtag, using pytest"""

import pytest

import galleries.galleryms
import galleries.relatedtag

GALLERIES = [
    galleries.galleryms.Gallery({"Tags": galleries.galleryms.TagSet(tagset)})
    for tagset in [set("abc"), set("cde"), set("efg"), set("xyz")]
]


def test_get_related_tags():
    query = galleries.galleryms.ConjunctiveSearchGroup()
    tag_fields = {"Tags"}
    related_tags = list(
        galleries.relatedtag.get_related_tags(GALLERIES, query, tag_fields)
    )
    assert len(related_tags) == 10
    # Because query is empty, overlap coeffs and frequencies should all be 1.0.
    assert all(
        tag.overlap_coefficient() == 1.0 and tag.frequency() == 1.0
        for tag in related_tags
    )
    assert all(tag.query is query for tag in related_tags)


@pytest.mark.parametrize("field_settings", [None, ()])
def test_results_table(field_settings):
    printer = galleries.relatedtag.results_table(field_settings)
    assert set(printer.formats) <= set(printer.columns)
    assert len(printer.columns) == len(printer.table.columns)
    assert not printer.table.rows
