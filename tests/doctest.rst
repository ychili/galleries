This file contains some interactive examples that, using ``doctest``,
serve as quick tests for some of this package's core classes.
They fill the gap between “too long or complex to fit in a docstring”
and “not yet turned into a unit test case.”

Test CSV parsing
----------------

Use ``StrictReader`` which checks for field mismatches from short or
long rows.

>>> from galleries.util import StrictReader
>>> fieldnames = "field1,field2"
>>> file = [fieldnames, "data1,data2"]
>>> r = StrictReader(file)
>>> r.fieldnames
['field1', 'field2']
>>> list(r)
[Gallery({'field1': 'data1', 'field2': 'data2'})]
>>> short_row = "data1 but not data2"
>>> r = StrictReader([fieldnames, short_row])
>>> list(r)
Traceback (most recent call last):
    ...
galleries.util.MissingFieldError: line 2: 1 missing field(s) in row: ['data1 but not data2']

Test query logic
----------------

Create a ``Query`` from a series of search terms.

>>> from galleries.galleryms import ArgumentParser
>>> ap = ArgumentParser()
>>> ap.parse_argument("tok1")
(WholeSearchTerm('tok1'), None)
>>> ap.parse_argument("field:tok1")
(WholeSearchTerm('tok1', fields=['field']), None)
>>> ap.parse_argument("~field:tok1")
(WholeSearchTerm('tok1', fields=['field']), '~')
>>> ap.parse_argument("rating=1")
(NumericCondition(<built-in function eq>, 1, fields=['rating']), None)
>>> ap.parse_argument("c=lt4")
(NumericCondition(<built-in function lt>, 4, fields=['c']), None)
>>> ap.parse_argument("n[field]=le8")
(CardinalityCondition(<built-in function le>, 8, fields=['field']), None)
>>> ap.parse_argument("g:tok%")
(WildcardSearchTerm('tok*', fields=['g']), None)
>>> ap.parse_argument("#c")
Traceback (most recent call last):
    ...
galleries.galleryms.ArgumentParsingError: #c
>>> ap.parse_args(["tok1", "tok2"])
Query(conjuncts=[WholeSearchTerm('tok1'), WholeSearchTerm('tok2')])
>>> ap = ArgumentParser(["TagField1", "TagField2"])
>>> ap.parse_args(["tok1", "~tok2"])
Query(conjuncts=[WholeSearchTerm('tok1', fields=['TagField1', 'TagField2'])], negations=[WholeSearchTerm('tok2', fields=['TagField1', 'TagField2'])])

A ``Query`` can then match a ``Gallery``.

>>> ap = ArgumentParser(["Tags"])
>>> # Match galleries tagged with "scotsman" but not "englishman"
>>> query = ap.parse_args(["scotsman", "~englishman"])
>>> from galleries.galleryms import Gallery
>>> query.match(Gallery(Tags="scotsman englishman"))
False
>>> query.match(Gallery(Tags="scotsman welshman"))
True
>>> query.match(Gallery(Tags="irishman"))
False
>>> # Wildcard match
>>> query = ap.parse_args(["%man"])
>>> query.match(Gallery(Tags="human"))
True

Test refresh logic
------------------

Test the ``refresh.Gardener``.

>>> from galleries.refresh import Gardener
>>> gard = Gardener()
>>> gard.set_normalize_tags("Field1", "Field2")
>>> rows = [Gallery(Field1=" tag2 tag1", Field2="TAG3 TAG4")]
>>> for gallery in gard.garden_rows(rows):
...     str(gallery["Field1"]), str(gallery["Field2"])
...
('tag1 tag2', 'tag3 tag4')
>>> from galleries.galleryms import RegularImplication
>>> implications = [RegularImplication("tag1", "tag5")]
>>> gard.set_imply_tags(implications, "Field1")
>>> for gallery in gard.garden_rows(rows):
...     str(gallery["Field1"]), str(gallery["Field2"])
...
('tag1 tag2 tag5', 'tag3 tag4')

Test the ``refresh.TagActionsObject``.

>>> from galleries.refresh import TagActionsObject
>>> tao = TagActionsObject()
>>> tao.update({"implications": {"car": "vehicle"}})
>>> tao.get_implicator().implications
{RegularImplication('car', 'vehicle')}
>>> tao.update({"aliases": {"forest": "tree"}})
>>> tao.get_implicator().aliases
ChainMap({'forest': 'tree'})

Test implication by ``Implicator``.

>>> from galleries.galleryms import Implicator, RegularImplication, TagSet
>>> i = Implicator([RegularImplication("car", "vehicle"), RegularImplication("bus", "vehicle")])
>>> i.find_cycle()
>>> tagset = TagSet(["car", "dog"])
>>> i.implicate(tagset)
>>> sorted(tagset)
['car', 'dog', 'vehicle']

Test the ``refresh.WordMultiplier``.

>>> from galleries.refresh import WordMultiplier
>>> wm = WordMultiplier()
>>> wm.add_set("letters", "ABC")
>>> wm.add_set("numbers", "123")
>>> sorted(wm.chain(["letters", "numbers"], join="".join))
[('A1', '1'), ('A2', '2'), ('A3', '3'), ('B1', '1'), ('B2', '2'), ('B3', '3'), ('C1', '1'), ('C2', '2'), ('C3', '3')]

Test tabulated output
---------------------

The ``Tabulator`` class has some recognized limitations. It will not
work with strings containing characters that occupy more than one
terminal column. Nevertheless, here is an example of normal usage, which
we can at least use to test for regressions.

>>> from galleries.galleryms import FieldFormat, Tabulator
>>> ff = {'A': FieldFormat(10), 'B': FieldFormat(FieldFormat.REM), 'C': FieldFormat(30)}
>>> tab = Tabulator(ff, total_width=73)
>>> rows = [
... {'A': 'Simon',
...  'B': 'Lorem ipsum dolor sit amet, consectetur adipiscing elit',
...  'C': 11.0},
... {'A': 'Clifford',
...  'B': 'Ut enim ad minim veniam, quis nostrud exercitation',
...  'C': 1.3411111111111111},
... {'A': 'Caramel',
...  'B': 'Excepteur sint occaecat cupidatat non proident',
...  'C': 0.9948266942576306}]
>>> for line in tab.tabulate(rows):
...     print(line.rstrip())
 Simon     Lorem ipsum dolor sit amet, consectetur    11.0
           adipiscing elit
 Clifford  Ut enim ad minim veniam, quis nostrud      1.3411111111111111
           exercitation
 Caramel   Excepteur sint occaecat cupidatat non      0.9948266942576306
           proident
