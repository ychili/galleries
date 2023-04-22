# tagcount.py
#
"""Count total tag occurrences."""

from __future__ import annotations

import collections
import csv
import logging
import statistics
from collections.abc import Iterable

from .galleryms import TagSet
from .util import check_field_names, tagsets_from_rows

log = logging.getLogger(__name__)


def tag_counts(tagsets: Iterable[TagSet]) -> collections.Counter[str]:
    """Return a counter of unique tags in *tagsets*."""
    counter: collections.Counter[str] = collections.Counter()
    for tagset in tagsets:
        counter.update(tagset)
    return counter


def count(reader: csv.DictReader, tag_fields: list[str], reverse: bool = False) -> int:
    """Print tag counts + tag names from *tag_fields* in *reader*.

    If *reverse* is True, print in ascending order.
    """
    if (status := check_field_names(reader.fieldnames, tag_fields)) is not None:
        return status
    tag_sets = tagsets_from_rows(reader, tag_fields)
    by_count = tag_counts(tag_sets).most_common()
    # by_count[0][1] is width of largest number in table
    just = len(str(by_count[0][1])) if by_count else 0
    counts = reversed(by_count) if reverse else by_count
    for tag, tagcount in counts:
        print(f"{tagcount:>{just}}\t{tag}")
    return 0


def summarize(reader: csv.DictReader, tag_fields: list[str]) -> int:
    """Print statistical summary of *tag_fields* in *reader*."""
    if (status := check_field_names(reader.fieldnames, tag_fields)) is not None:
        return status
    tag_sets = list(tagsets_from_rows(reader, tag_fields))
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
