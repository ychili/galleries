This file contains some interactive examples that, using ``doctest``,
serve as quick tests for some of this package's core classes.
They fill the gap between “too long or complex to fit in a docstring”
and “not yet turned into a unit test case.”

Test query logic
----------------

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
>>> ap.parse_argument("g:tok%")
(WildcardSearchTerm('tok*', fields=['g']), None)
>>> ap.parse_args(["tok1", "tok2"])
Query(conjuncts=[WholeSearchTerm('tok1'), WholeSearchTerm('tok2')])
>>> ap = ArgumentParser(["TagField1", "TagField2"])
>>> ap.parse_args(["tok1", "~tok2"])
Query(conjuncts=[WholeSearchTerm('tok1', fields=['TagField1', 'TagField2'])], negations=[WholeSearchTerm('tok2', fields=['TagField1', 'TagField2'])])

Test refresh logic
------------------

Test the ``refresh.Gardener``.

>>> from galleries.refresh import Gardener
>>> gard = Gardener()
>>> gard.set_normalize_tags("Field1", "Field2")
>>> rows = [{"Field1": " tag2 tag1", "Field2": "TAG3 TAG4"}]
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
