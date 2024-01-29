# tagcount.py
#
"""Count total tag occurrences."""

from __future__ import annotations

import collections
import itertools
import logging
import statistics
from collections.abc import Iterable

from . import PROG
from .galleryms import TagSet

log = logging.getLogger(PROG)


def tag_counts(tag_sets: Iterable[TagSet]) -> collections.Counter[str]:
    """Return a counter of unique tags in *tag_sets*."""
    return collections.Counter(itertools.chain.from_iterable(tag_sets))


def count(tag_sets: Iterable[TagSet], reverse: bool = False) -> int:
    """Print tag counts + tag names from *tag_sets*.

    If *reverse* is True, print in ascending order.
    """
    by_count = tag_counts(tag_sets).most_common()
    # by_count[0][1] is width of largest number in table
    just = len(str(by_count[0][1])) if by_count else 0
    counts = reversed(by_count) if reverse else by_count
    for tag, tagcount in counts:
        print(f"{tagcount:>{just}}\t{tag}")
    return 0


def summarize(tag_sets: Iterable[TagSet]) -> int:
    """Print statistical summary of *tag_sets*."""
    tag_sets = list(tag_sets)
    print("TOTALS")
    print(f"  galleries   {len(tag_sets)}")
    counts = tag_counts(tag_sets).values()
    total_tags = sum(counts)
    print(f"  tags        {total_tags}")
    print(f"  unique_tags {len(counts)}")
    print("AVERAGES")
    print(f"  galleries_per_tag {total_tags / len(counts)}")
    print(f"  tags_per_gallery  {total_tags / len(tag_sets)}")
    print("TAG COUNTS")
    print(f"  t_max    {max(counts)}")
    print(f"  t_min    {min(counts)}")
    counts_mu = statistics.mean(counts)
    print(f"  t_mean   {counts_mu}")
    print(f"  t_median {statistics.median(counts)}")
    print(f"  t_mode   {statistics.mode(counts)}")
    print(f"  t_stdev  {statistics.pstdev(counts, counts_mu)}")
    print("GALLERY SIZES")
    sizes = [len(tag_set) for tag_set in tag_sets]
    print(f"  g_max    {max(sizes)}")
    print(f"  g_min    {min(sizes)}")
    sizes_mu = statistics.mean(sizes)
    print(f"  g_mean   {sizes_mu}")
    print(f"  g_median {statistics.median(sizes)}")
    print(f"  g_mode   {statistics.mode(sizes)}")
    print(f"  g_stdev  {statistics.pstdev(sizes, sizes_mu)}")
    return 0
