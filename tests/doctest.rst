Test query logic.

>>> from galleries.galleryms import ArgumentParser
>>> ap = ArgumentParser()
>>> ap.parse_argument("tok1")
(WholeSearchTerm('tok1', *[]), None)
>>> ap.parse_argument("field:tok1")
(WholeSearchTerm('tok1', *['field']), None)
>>> ap.parse_argument("~field:tok1")
(WholeSearchTerm('tok1', *['field']), '~')
>>> ap.parse_argument("rating=1")
(NumericCondition(<built-in function eq>, 1, *['rating']), None)
>>> ap.parse_argument("c=lt4")
(NumericCondition(<built-in function lt>, 4, *['c']), None)
>>> ap.parse_argument("g:tok%")
(WildcardSearchTerm('tok*', *['g']), None)
>>> ap.parse_args(["tok1", "tok2"])
Query(conjuncts=[WholeSearchTerm('tok1', *[]), WholeSearchTerm('tok2', *[])])
>>> ap = ArgumentParser(["TagField1", "TagField2"])
>>> ap.parse_args(["tok1", "~tok2"])
Query(conjuncts=[WholeSearchTerm('tok1', *['TagField1', 'TagField2'])], negations=[WholeSearchTerm('tok2', *['TagField1', 'TagField2'])])

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

Test the ``refresh.UnifiedObjectFormat``.

>>> from galleries.refresh import UnifiedObjectFormat
>>> uof = UnifiedObjectFormat({"implications": {"car": "vehicle"}})
>>> list(uof.get_implications())
[(None, {RegularImplication('car', 'vehicle')})]
>>> uof.update({"aliases": {"forest": "tree"}})
>>> list(uof.get_aliases())
[(None, {'forest': 'tree'})]

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
