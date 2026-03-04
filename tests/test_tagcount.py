"""Unit tests for tagcount, using pytest"""

import hypothesis
import hypothesis.strategies as st

import galleries.galleryms
import galleries.tagcount


# Use numbers as tags.
# 0-5 are actual tags in the tag sets. -2 and -1 represent search misses.
@hypothesis.given(
    tag_sets=st.iterables(st.sets(st.integers(0, 5).map(str))),
    tags=st.lists(st.integers(-2, 2).map(str)),
)
def test_tag_counts_by_tag_search(tag_sets, tags):
    """The Counter returned contains only the set of tags searched for."""
    counts = galleries.tagcount.tag_counts(tag_sets, tags)
    print(counts)
    assert counts.keys() == set(tags)
    assert all(counts[tag] == 0 for tag in map(str, range(-3, 0)))


tag_sets_strategy = st.iterables(st.builds(galleries.galleryms.TagSet))


@hypothesis.given(tag_sets_strategy, st.booleans())
def test_fuzz_count(tag_sets, reverse):
    assert galleries.tagcount.count(tag_sets, reverse=reverse) == 0


@hypothesis.given(tag_sets_strategy)
def test_fuzz_summarize(tag_sets):
    assert galleries.tagcount.summarize(tag_sets) == 0
