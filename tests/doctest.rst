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
