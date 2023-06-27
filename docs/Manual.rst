==================
 Galleries Manual
==================

.. contents::
   :depth: 2

------
Basics
------

A "gallery" is a directory with some number of files that you wish to tag.
A "collection" is a set such galleries that share a parent directory,
the root directory of the collection, and share a common system of tags.
For each collection there is one file containing its data table,
formatted in CSV (comma-separated values),
and one `collection configuration file`_.
These two files live in a sub-directory of the collection's root
directory.

The names of these directories and files can be customized, but, using
the default names, a basic collection structure would look like
this::

    .
    ├── .galleries
    │   ├── db.conf
    │   └── db.csv
    ├── [galleries...]

Each line of the CSV file (i.e. each row of the CSV table), contains the
metadata for one gallery.
A minimum CSV table contains a path field, a count field,
and one tag field.
Field names can be customized in the `collection configuration file`_,
but here is an example of a collection data table
using the default field names::

    Path,Count,Tags
    Animal Pictures,25,deer fox otter
    Car Pictures/Mazda,4,blue_car red_car
    Car Pictures/Mercury,5,blue_car green_car

The path field (config key: `PathField`_)
should contain the path to the gallery
relative to the root directory of the collection.
The count field (config key: `CountField`_)
should contain the number of regular files in the gallery.
It is updated automatically by the `refresh`_ command,
so you shouldn't need it edit it manually.
A gallery's tags go in one or more tag fields
(config key: `TagFields`_).
The above example has a single tag field called "Tags".
Within a field, tags are separated from each other by a space.
See "`Tagging galleries`_" below for more info on tags.

-------------------
General Usage Guide
-------------------

This program's sub-commands (except for `init`_) expect to be
preceded by an argument to the ``-c`` or ``--collection`` option
(see `General options`_).
The argument should be a path to the root directory of a valid
collection, and it defaults to the current working directory.
Should this become too unwieldy, see the `Global configuration`_
section for how to set up short names for your collections.

Initializing a new collection
=============================

Run ``galleries init`` in the root directory of the collection to create
a new configuration file, by default named ``.galleries/db.conf``.
Unless the option ``--bare`` is given
(see `init`_ for full description of options),
the new file will contain the built-in, default values
for many configuration keys.
Customize them at this point if you wish.
Run ``galleries traverse`` to create a new CSV file containing
the enumerated directory tree of the collection.
The PathField will contain the directory (gallery) name,
and the CountField will contain its file count.
The TagFields will be empty.
Add the option ``-o-`` to preview the new table before it's written to disk
(see `traverse`_ for full description of options).
You can always remove incorrect entries later.

The `refresh`_ command will update file counts automatically
(unless the option ``--no-check`` is given)
and also sort rows by the field `SortField`_.

Tagging galleries
=================

Start tagging your galleries by adding tags in fields belonging to
`TagFields`_.
A tag field can contain zero or more tags.
Within a field, each tag is separated by spaces.
Therefore a tag itself cannot contain spaces.

The `refresh`_ command will normalize tags in tag fields,
ensuring that each tag field contains a proper tag set:
no duplicate tags, each tag sorted, lowercased,
and separated by a single space.

The `count`_ command counts up how many times each tag appears in a
tag field.
It prints the list out in descending order,
so pipe the results to **tac**\ (1) to see the most common tags last.
Pipe the results to **grep**\ (1) to filter tags by regular expression.

Gardening tag sets
==================

In addition to normalizing tags and updating the gallery file count,
the `refresh`_ command will optionally apply implications and aliases
to tag sets in tag fields.
Implications add tags to a tag set that are implied by tags
already in the set.
Aliases replace aliased tags.

So, for a hypothetical implication where tag A implies tag B,
:math:`A \implies B`,
if tag A is found in the tag set, the implication adds tag B to the set.
Likewise, for a hypothetical alias where tag A is aliased to tag B,
:math:`A \to B`,
if tag A is found in the tag set, the alias will replace it with tag B.

Implications and aliases can be created in a "TagActions file."
The argument to the config key `TagActions`_ in the [refresh] section
will be interpreted as a TagActions file.
The file should be written in JSON format or,
if the file has a "toml" extension, `TOML format`_.

.. _TOML format: https://toml.io

For basic tag implication and aliasing support,
create two top-level tables called "implications" and "aliases".\ [#]_
Every key–value pair in the implications table will create an
implication from key to value.
Every key–value pair in the aliases table will alias
the key to its value.
An example in TOML format::

    [implications]
    "truck" = "land_vehicle"
    "car" = "land_vehicle"
    [aliases]
    "automobile" = "car"

.. [#] They are called tables in the TOML format.
       The JSON equivalent is an object.

To imply multiple tags from a single tag,
create a table called "multi-implications"
(duplicate keys won't work in either JSON or TOML).
The values in this table should be an array of tags.
Implications will be created
from the key tag to each of the tags in the array.

There is support for creating numerous implications
by multiplying strings in a way that would be tedious and error-prone
to do by hand using a table called "descriptors".
What possible use is this?
When you have many tags that take the form "adjective_noun",
you would like to have the qualified tag imply the base noun tag.
Such implications generally take the form
"adjective_noun" :math:`\implies` "noun".
For example, the tag "green_shirt" naturally implies the tag "shirt".
But, rather than manually specifying a separate implication for each
combination of colors and items of clothing,
the descriptors table will do the work of joining strings
and creating implications.

The descriptors table relies on two sub-tables called
"descriptors.chains" and "descriptors.sets".
The sets sub-table should contain named sets of strings that are to be
multiplied together by the chains sub-table.
The chains sub-table does the work of generating implications for you.
Each entry creates a "chain" of implications.
For the keys, choose any name you want.
The values should be an array of (at least two) names of sets
created in the sets sub-table.
Each combination of strings from each set will be concatenated
(from left to right) with a single intervening underscore.
An implication will be created from the concatenated string to
its right-hand constituent.

Here is an example (in TOML format) of using the descriptors table to
associate "adjective_noun" tags to base noun tags::

    [descriptors.sets]
    colors = ["red", "blue", "green"]
    things = ["shirt", "car", "airplane"]
    [descriptors.chains]
    colored_things = ["colors", "things"]

This example will create implications for every combination of
*color* + *thing* :math:`\implies` *thing* —
"red_shirt" to "shirt", "blue_shirt" to "shirt", etc.,
"red_car" to "car", etc.

If there are three or more set names in a chain array,
the process works the same,
concatenating and generating from left to right.
Suppose another set called "styles" were added to the preceding example
containing the strings "solid" and "striped".
The chain ``["styles", "colors", "things"]`` would,
*in addition* to the implications generated by the preceding example,
generate the implications "solid_red_car" :math:`\implies` "red_car"
and "striped_green_airplane" :math:`\implies` "green_airplane",
and so forth.
In this way layers of qualifiers can be supported and chains of
tag implications maintained,
limited only by the semantic resources of the English language
and complexity of your tagging system.

You can merge strings from descriptor sets into supercategories
using the sub-table "descriptors.unions".
The unions sub-table associates an array of set names
(as defined in the sets sub-table) with a new name.
This new name can be used in a chains declaration
and represents the union (merger) of its constituent sets.
Unions may contain other unions,
but cannot refer to ones that have not been defined yet.
In this situation, the order in which unions are defined matters.

The set of implications and aliases created by a TagActions file are
validated for logical consistency in three ways.

(1) No circular implications.
    You cannot create a tag implications or series of tag implications
    where a tag ends up implying itself, as in
    :math:`A \implies B \implies A`.
    Without this check the implication process would loop infinitely.

(2) No transitive aliases.
    You cannot alias a tag to a tag that is itself aliased, as in
    :math:`A \to B` **and** :math:`B \to C`.
    Aliasing is a one-step process that occurs before implication,
    so this would not work.
    In this situation, alias A directly to C.

(3) No aliased implications.
    The two tags forming an implication
    cannot be aliased to another tag,
    for the same reason as (2).

While you are writing rules in your TagActions file (or files),
you can perform these three checks *without* then updating the table
using the `refresh`_ command's ``--validate`` option.

TagActions respect the `ImplicatingFields`_ key of [refresh]
and will only be applied to fields named therein.
For finer control, you can specify which rules apply to which fields or
groups of fields in the TagActions file itself.
If either or both of the top-level keys "fieldnames" and "fieldgroups" are
given, then parsing will ignore ImplicatingFields and assign rules to the
fields named by these settings. The "fieldnames" key expects an array of field
names. There should be a correspondingly named top-level table for each field
name itself containing at least one of the tables for creating rules discussed
above (i.e. implications, aliases, and descriptors). These rules will only be
applied to the named field. The "fieldgroups" key should be a table whose
values are arrays of field names. For each key there should be a
correspondingly named top-level table, the rules in which will be applied to
the fields named in that array.

An example in TOML format of defining different rules for different
fields::

    fieldnames = ["Field A"]

    [fieldgroups]
    "B + C" = ["Field B", "Field C"]

    ["Field A".implications]
    # Implications defined in this table will be applied
    # just to Field A.

    ["B + C".implications]
    # Implications defined in this table will be applied
    # to both Field B and Field C.

    ["B + C".aliases]
    # Same with aliases and descriptors tables

Querying the table
==================

The `query`_ command prints galleries that match a given set of
search terms.
Here is a summary of search term syntax:

``tag1 tag2``
    Search for galleries that have both tag1 and tag2
    in any tag field.

``+tag1 +tag2``
    Search for galleries that have either tag1 or tag2
    in any tag field.

``~tag1 ~tag2``
    Search for galleries that have neither tag1 nor tag2
    in any tag field.

``tag1 %_thing``
    Search for galleries that have tag1
    and at least one tag ending with "_thing"
    in any tag field.

``GenTags:tag1``
    Search for galleries where the GenTags field (not any tag field)
    has tag1.

``Count=0``
    Search for galleries where the Count field is equal to 0.

``Count=ge10``
    Search for galleries where the Count field is
    greater than or equal to 10.

``n[GenTags]=lt6``
    Search for galleries that have fewer than 6 tags
    in the GenTags field.

Field names in search terms can be abbreviated as long as
the abbreviation is unambiguous.

By default, galleries are printed as CSV rows with no extra formatting
(``--format=none``).
To print query results with each field as a wrapped column,
create a "field formats file."
The name of this file is passed to the `FieldFormats`_ configuration key.
The default name is ``tableformat.conf``.
The field formats file should contain the name of field you wish to include
in the query results, one per line,
followed by its formatting parameters.
Each argument is separated by tabs or spaces.
Therefore, tabs or spaces within arguments must be quoted.

Here is an example field formats file::

    # Comments are okay
    Path  30 "bright blue" "" "bold"
    Count 3
    Tags  REM

This means:
for the Path field dedicate at most 30 terminal columns before wrapping
and make the text bright blue and bold (with default background color),
dedicate at most 3 columns to the Count field,
and dedicate the remaining available terminal columns to the Tags field.
The formatter will use all available columns in your terminal window.

Here is what each field in the field formats file does
(in left-to-right order):

(1) The *field name* is required.
    Fields whose names aren't listed in the field formats file or whose
    arguments are invalid won't appear in `query`_'s formatted output.

(2) A *maximum width* argument is required.
    Wrap the contents of this field to a column no wider
    than *maximum width*.
    Note the resulting column width may be less than this maximum
    if the contents don't need it.
    The special value ``REM`` can be given here to indicate
    "use remaining space for this column".

(3) A *foreground color* argument is optional.
    Color the text *foreground color*.
    Choices include:
    black, red, green, yellow, blue,
    magenta, cyan, white, bright black,
    grey, bright red, bright green,
    bright yellow, bright blue, bright magenta,
    bright cyan, bright white, or ``""`` for default color.

(4) A *background color* argument is optional.
    Color the background *background color*.
    Choices are the same as for (3).

(5) An *effect* argument is optional.
    Use the *effect* terminal text effect.
    Choices include:
    bold, faint, dim, italic, underline,
    reverse video, invert, or ``""`` for none.

Once the field formats file is set up, enable formatted output
by setting the value of the ``--format`` option
or the `Format`_ configuration key in the [query] section.
A value of **format** means always format.
A value of **auto** will format if it detects that standard output
is connected to a terminal (and not, for example, a pipe).

Analyzing tag relationships
===========================

The `related`_ command can be used to analyze the relative
co-occurrence of different tags.
It prints a list of tags that frequently co-occur with a given tag or tags.

Global configuration
====================

While the `collection configuration file`_ contains settings for each
collection, this program can optionally be configured on a
user-wide level using two files,
the `global configuration file`_, named ``config``,
and the `global collection paths file`_, named ``collections``.
These files should live in the same directory.
For most users, this directory should be at ``~/.config/galleries``,
though see `File locations`_ for alternate locations.

In the global collection paths file,
you can specify short names for your collections.
These short names, when passed to the ``--collection`` option,
will be expanded to their full path value.
They can even be abbreviated as long as the abbreviation is unambiguous.
Here is an example::

    # ~/.config/galleries/collections
    [pics]
    Root: ~/Pictures/Galleries
    [oldpics]
    Root: /mnt/windows/Users/Albert/My Pictures

With this, the argument ``-c pics`` will look for a section named "pics"
in the file and get the full path from the value of the key Root.
In this example that would be ``~/Pictures/Galleries``.

What if the option ``-c`` is omitted?
The default is to see if the current working directory is a valid
collection, but you can set a default collection in your
global configuration file in the [global] section
using the option `Default`_.
The following example sets "pics" as the default collection::

    # ~/.config/galleries/config
    [global]
    Default: pics

Consult the sections for the `global configuration file`_ and
the `global collection paths file`_ for the other configuration options
they enable.

-----------------
Command Reference
-----------------

Many commands' arguments have defaults that can be configured via
configuration file.


General options
===============

init
====

Initialize a new collection.

Usage
-----

.. parsed-literal::

    **galleries** [*general_options* ...] **init**
        [*init_options* ...] [*directory*]

The **init** command initializes a new collection
rooted in *directory*, which is created if it does not exist.
If *directory* is omitted it defaults to the current working directory.
Then, **init** creates a galleries sub-directory,
by default named ``.galleries``
but configurable with the `GalleriesDir`_ setting.
Lastly, **init** creates a default `collection configuration file`_,
by default named ``db.conf``
but configurable with the `ConfigName`_ setting.
**init** will refuse to overwrite an existing file with that name.

Options
-------

-h, --help
    Show help message for **init**.

--bare
    Create an empty `collection configuration file`_
    instead of the default containing the built-in settings.

--template=DIRECTORY
    Recursively copy files from *DIRECTORY* into the galleries
    sub-directory.
    Files with names that start with a dot are not copied.
    Default: value of init.\ `TemplateDir`_.

Configuration
-------------

If init.\ `TemplateDir`_ is set (in the `global configuration file`_),
it is used as the argument to ``--template``.
This setting can by bypassed with the ``--bare`` option.

The `global collection paths file`_ is consulted when naming file paths.
If *directory* matches a `Root`_ entry in this file,
then the `GalleriesDir`_ and `ConfigName`_ entries from that section
will be used, falling back to the entries from the section [DEFAULT].

traverse
========

Enumerate directory tree.

Usage
-----

.. parsed-literal::

    **galleries** [*general_options* ...] **traverse**
        [*traverse_options* ...]

The **traverse** command creates a new CSV file containing the
enumerated directory tree of the selected collection.
The directory paths are placed in the collection's path field,
and their file counts are placed in the collection's count field.
All tag fields are left empty.

Options
-------

--h, --help
    Show help message for **traverse**.

--force
    Overwrite existing CSV file.

--leaves
    Only enumerate directories that have no sub-directories
    of their own.

-o FILE, --output=FILE
    Write CSV to *FILE*.
    If specified, this option will always overwrite existing files.
    Default: value of db.\ `CSVName`_.

Configuration
-------------

Field names are configurable with the following three settings:
the path field with db.\ `PathField`_,
the count field with db.\ `CountField`_,
and tag fields with db.\ `TagFields`_.

count
=====

Print counts of tags occurring in tag field(s).

Usage
-----

.. parsed-literal::

    **galleries** [*general_options* ...] **count**
        [*count_options* ...] [*field* ...]

The **count** command totals up the occurrence of tags appearing in
the tag field *field* and prints them in descending order.
If more than one tag field is given, all their tags are treated as one,
merged field.
If *field* is omitted it defaults to the value of count.\ `TagFields`_.

Options
-------

--h, --help
    Show help message for **traverse**.

-i FILE, --input=FILE
    Read CSV from *FILE*.
    Default: value of db.\ `CSVName`_.

-S, --summarize
    Print statistical summary of tag counts.

query
=====

Print galleries search term(s).

Usage
-----

.. parsed-literal::

    **galleries** [*general_options* ...] **query**
        [*query_options* ...] [*search_term* ...]

Options
-------

-h, --help
    Show help message for **query**.

-f FIELD, --field=FIELD
    Use *FIELD* as the default tag field for *search_term*\ s that don't
    have their own field specifiers.
    This option can be passed more than once to build up a list of
    tag fields.
    Default: value of query.\ `TagFields`_.

-F WHEN, --format=WHEN
    Control output format.
    *WHEN* can be omitted or one of **none**, **format**, or **auto**.
    The argument **none** selects no formatting.
    That is, rows are printed as they are in CSV format.
    The argument **format** selects formatted output, where fields are
    printed in wrapped columns.
    To use formatted output, a field formats file must be provided
    containing formatting instructions.
    The argument **auto** will select formatted output if printing to
    a terminal, otherwise unformatted output.
    The ``--format`` option with no argument is the same as
    ``--format=auto``.
    Default: value of query.\ `Format`_.

-i FILE, --input=FILE
    Read CSV from *FILE*.
    Default: value of db.\ `CSVName`_.

-r, --reverse
    Sort results in descending order.
    Default: ascending sort.

-s FIELD, --sort=FIELD
    Sort results by *FIELD*.
    Default: don't sort.

--field-formats=FILE
    Parse field formats from *FILE*.
    Default: value of query.\ `FieldFormats`_.

refresh
=======

Update galleries' info and garden tag sets.

Usage
-----

.. parsed-literal::

    **galleries** [*general_options* ...] **refresh**
        [*refresh_options* ...]

The **refresh** command performs a number of maintenance tasks on the
data table.
It ensures that each value belonging to a tag field contains a proper
tag set: no duplicate tags, each tag sorted, lowercased,
and separated by a single space.
It will check each gallery's path and update its file count, exiting
with an error if a path is misspelled or has been deleted.
`Implications and aliases`_ will be applied to tag sets if requested.
Galleries are sorted, and before the new file is written the old one is
backed up with a simple backup suffix.

Options
-------

-h, --help
    Show help message for **refresh**.

--no-check
    Skip updating galleries' file counts. Just garden tag sets.

--suffix=SUFFIX
    Back up the old file with *SUFFIX* appended.
    Default: value of refresh.\ `BackupSuffix`_.

--validate
    Check TagActions files for correctness and exit.

Implications and aliases
------------------------

Implications and aliases can be used to automatically add or replace
tags in tag sets every time **refresh** is run.
The value of refresh.\ `TagActions`_, if it is set, will be parsed as a
"TagActions file" containing instructions for creating implications and
aliases.
See the section on "`Gardening tag sets`_" for the format of this file,
as well as description of what implications and aliases can do.
Before applying these actions, **refresh** will check them for
correctness.
The ``--validate`` option can be used to perform these checks without
modifying any tag sets.

Configuration
-------------

For its basic functions, **refresh** gets the path of the data table
from the setting db.\ `CSVName`_ and the names of tag fields from
refresh.\ `TagFields`_.
The path field is set by refresh.\ `PathField`_, and the count field is
set by refresh.\ `CountField`_.
The field by which galleries will be sorted is set by
refresh.\ `SortField`_.
If refresh.\ `ReverseSort`_ is set to true, galleries will be sorted in
descending sort order (Z to A instead of A to Z).

If refresh.\ `ImplicatingFields`_ is set, implications and aliases will
only be applied to tag sets in those fields.

related
=======

Print tags that frequently co-occur.

Usage
-----

.. parsed-literal::

    **galleries** [*general_options* ...] **related**
        [*related_options* ...] *tag* [*tag* ...]

The **related** command prints a table of other tags that are similar to
*tag*.
The table includes the tags' names, their total count, and a selection
of similarity metrics.
This can be used for finding related tags that frequently appear in the
same tag sets together.

Options
-------

-h, --help
    Show help message for **related**.

-f NAME, --field=NAME
    Search for *tag*\ (s) in *FIELD*.
    This option can be passed more than once to build up a list of
    tag fields.
    Default: value of related.\ `TagFields`_.

-i FILE, --input=FILE
    Read CSV from *FILE*.
    Default: value of related.\ `CSVName`_.

-l N, --limit=N
    Limit the number of results per *tag* to a number *N*.
    *N* can be **0** for no limit on the number of results.
    Default: value of related.\ `Limit`_.

-s NAME, --sort=NAME
    Sort results by *NAME*, where *NAME* is one the field names in the
    table of results (tag name, tag count, or similarity metric).
    Default: value of related.\ `SortMetric`_.

-w TERM, --where=TERM
    Only analyze tags from galleries that match *TERM*, where *TERM* is
    a search term with the same syntax as used by the `query`_ command.
    This option can be passed more than once to build up a list of
    search terms.
    Default: value of related.\ `Filter`_.

-----------------------
Configuration Reference
-----------------------

File locations
==============

The `Global configuration file`_, ``config``, and the `Global
collection paths file`_, ``collections``, will be searched for in the
following sequence of directories:

(1) ``${GALLERIES_CONF}`` if it is set
(2) ``${XDG_CONFIG_HOME}/galleries/config``
(3) ``${HOME}/.config/galleries/config`` if ``$XDG_CONFIG_HOME`` is unset

Argument types
==============

Collection configuration file
=============================

[db]
----

CSVName
```````
:Type: Path
:Default value:

PathField
`````````
:Type:
:Default value:

CountField
``````````
:Type:
:Default value:

TagFields
`````````
:Type:
:Default value:

[query]
-------

FieldFormats
````````````
:Type: Path
:Default value: tableformat.conf

Format
``````
:Type:
:Default value: None

[refresh]
---------

BackupSuffix
````````````
:Type: String
:Default value: .bak

ImplicatingFields
`````````````````
:Type:
:Default value:

ReverseSort
```````````
:Type: Boolean
:Default value: False

SortField
`````````
:Type:
:Default value:

TagActions
``````````
:Type: Path
:Default value:

[related]
---------

Filter
``````
:Type:
:Default value:

Limit
`````
:Type: Integer
:Default value: 20

SortMetric
``````````
:Type:
:Default value: cosine

Global configuration file
=========================

[global]
--------

Default
```````
:Type: Collection name
:Default value: None

[init]
------

TemplateDir
```````````
:Type: Path
:Default value: None

Global collection paths file
============================

Root
----

GalleriesDir
------------

ConfigName
----------
