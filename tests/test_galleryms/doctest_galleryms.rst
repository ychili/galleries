This file contains additional doctests for the ``galleryms`` module.

ArgumentParser
--------------

>>> from galleries.galleryms import ArgumentParser
>>> ap = ArgumentParser()
>>> parse = lambda *args: ap.parse_args(args).terms

Test these example queries
from the manual's section on "Querying the table":

>>> parse('tag1', 'tag2')
[WholeSearchTerm('tag1'), WholeSearchTerm('tag2')]
>>> parse('+tag1', '+tag2')
[DisjunctiveSearchGroup([WholeSearchTerm('tag1'), WholeSearchTerm('tag2')])]
>>> parse('~tag1', '~tag2')
[NegativeSearchGroup([WholeSearchTerm('tag1'), WholeSearchTerm('tag2')])]
>>> parse('tag1', '%_thing')
[WholeSearchTerm('tag1'), WildcardSearchTerm('*_thing')]
>>> parse('GenTags:tag1')
[WholeSearchTerm('tag1', fields=['GenTags'])]
>>> parse('Count=0')
[NumericCondition(<built-in function eq>, 0, fields=['Count'])]
>>> parse('Count=ge10')
[NumericCondition(<built-in function ge>, 10, fields=['Count'])]
>>> parse('n[GenTags]=lt6')
[CardinalityCondition(<built-in function lt>, 6, fields=['GenTags'])]

Test these example queries
from manual's examples for the query command:

>>> parse("a", "+b", "+c")
[WholeSearchTerm('a'), DisjunctiveSearchGroup([WholeSearchTerm('b'), WholeSearchTerm('c')])]
>>> parse("~a", "+b", "+c")
[NegativeSearchGroup([WholeSearchTerm('a')]), DisjunctiveSearchGroup([WholeSearchTerm('b'), WholeSearchTerm('c')])]
>>> parse("n[]=0")
[CardinalityCondition(<built-in function eq>, 0)]

Implication objects
-------------------

Test some properties of these objects like reconstructibility from their
``repr``, equality, and frozenness.

>>> from galleries.galleryms import RegularImplication, DescriptorImplication
>>> reg = RegularImplication("A", "C")
>>> eval(repr(reg)) == reg
True
>>> word = DescriptorImplication("word")
>>> eval(repr(word)) == word
True
>>> reg.consequent = "Conclusion"
Traceback (most recent call last):
    ...
dataclasses.FrozenInstanceError: cannot assign to field 'consequent'
