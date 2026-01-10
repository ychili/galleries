"""Unit tests for tagcount, using pytest"""

import hypothesis
import hypothesis.strategies

import galleries.galleryms
import galleries.tagcount

tag_sets_strategy = hypothesis.strategies.iterables(
    hypothesis.strategies.builds(galleries.galleryms.TagSet)
)


@hypothesis.given(tag_sets_strategy)
def test_fuzz_summarize(tag_sets):
    assert galleries.tagcount.summarize(tag_sets) == 0
