===========
 Galleries
===========

.. contents::

Basics
======

A "gallery" is a directory with some number of files that you wish to tag.
A "collection" is a parent directory of such galleries that will share a
common tagging system.
Files relating to the collection are stored in a sub-directory called
``.galleries``.
In this sub-directory there is a configuration file called ``db.conf``.
For each collection there is one file containing its data table,
formatted in CSV, comma-separated values.
The name of the CSV file is referred to in the configuration file by the
key "CSVName" in the section [db] (the default filename is ``db.csv``).
Each row of the CSV table contains the data for one gallery.
A minimum CSV table contains a path field, a count field,
and one tag field.
Field names are referred to in the configuration file by the following keys:

"PathField"
    This field should contain the path to the gallery,
    relative to the root directory of the collection.
    The default name is "Path".

"CountField"
    This field should contain the number of regular files in the gallery.
    It is updated automatically by the ``refresh`` command.
    The default name is "Count".

"TagFields"
    Place the name of each field containing the gallery's tags
    in a semicolon-separated list.
    Different categories of tags can be put in different tag fields.
    The default is a single tag field named "Tags".

Usage
=====

This program's sub-commands (except for ``init``) expect to be
preceded by an argument to the ``-c`` or ``--collection`` option.
The argument should be a path to the root directory of the collection
(it defaults to the current working directory).
See the `Global Configuration`_ section for how to set up short names
for your collections.

Initializing a new collection
-----------------------------

Run ``galleries init`` in the root directory of the collection to create
a new configuration file, ``.galleries/db.conf``.
Unless the option ``--bare`` is given, the new file will contain the
default values for many configuration keys.
Customize them at this point if you wish.
Run ``galleries traverse`` to create a new CSV file containing
the enumerated directory tree of the collection.
The PathField will contain the directory (gallery) name,
and the CountField will contain its file count.
The TagFields will be empty.
Use the option ``-o-`` to preview the new table before it's written to disk.
You can always remove incorrect entries later.

The ``refresh`` command will update file counts automatically
(unless the option ``--no-check`` is given)
and also sort rows by the value of PathField.

Tagging galleries
-----------------

Start tagging your galleries by adding tags in fields belonging to
TagFields.
A tag field can contain zero or more tags.
Each tag is separated by whitespace.
Therefore a tag cannot contain whitespace.

The ``refresh`` command will normalize tags in tag fields,
ensuring that each tag field contains a tag set:
no duplicate tags, each tag sorted, lowercased,
and separated by a single space.

Gardening tag sets
------------------

Implications, aliases, and removals
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In addition to normalizing tags and updating the gallery file count,
the ``refresh`` command will optionally apply implications, aliases,
and removals to tag fields.
Implications add tags to a tag set that are implied by tags
already in the set.
Aliases replace aliased tags.
Removals simply remove tags from a set if present.
The data for these actions are stored in files.
Two types of "implications files" are understood,
distinguished by file extension.
Files with extensions matching any of "dat", "txt", "asc", or "list"
are expected to contain "descriptor" implications,
while files with the "json" extension are expected to contain
"regular" implications.

Regular implications are straightforward.
The file must be a JSON formatted object containing
a series of key–value pairs relating one string to another,
each string representing one tag.
If the tag in the key is found in the tag set,
the tag in the value will be added to the set.

Descriptor implications are parsed from a file containing
string separated by whitespace,
each string representing the leading portion of a tag.
If this string is matched by the leading portion of a tag in a tag set,
the following portion of that tag will be added to the set,
minus one intervening underscore.
So, for example, if "green" is a descriptor implication string
and "green_shirt" is a tag in a tag set
that the implication is being applied to,
then the tag "shirt" will be added to the set.

Aliases are specified much like regular implications.
The file must be a JSON formatted object containing
a series of key–value pairs relating one string to another,
each string representing one tag.
If the tag in the key is found in the tag set,
it will be replaced with the tag in the value.

After all implications and all aliases have been applied
and no more tags can be added,
removals will be applied.
A removals file contains strings separated by whitespace,
each string representing one tag.
These tags will be removed from tag sets if they are present.
This can be useful for cleaning up tags added by descriptor implications
but which do not count as tags themselves.

Implications, aliases, and removals will be performed by ``refresh``
if the [refresh] section of the configuration file contains arguments to
any of the keys "Implications", "Aliases", or "Removals", respectively.
The arguments to these keys should be a semicolon-separated list of files.
Filenames are relative to the ``.galleries`` sub-directory of
your collection (the same as all filenames in the configuration).
Implications from each implications file and aliases from each alias file
will be applied in the order the files are listed.
Removals will be applied after that.
If this process should only be applied to a subset of TagFields,
add the "ImplicatingFields" key to the [refresh] section.

TagActions
~~~~~~~~~~

The "TagActions" file format is another way of creating rules against
which tag sets will be updated.
This format can create regular implications and aliases from one file.
The argument to the config key "TagActions" in the [refresh] section
will be interpreted as a TagActions file.
The file should be written in JSON format or,
if the file has a "toml" extension, `TOML format`_.

.. _TOML format: https://toml.io

For basic tag implication and aliasing support,
create two top-level tables called "implications" and "aliases".
Every key–value pair in the implications table will create a regular
implication from key to value.
Every key–value pair in the aliases table will alias
the key to its value.
An example in TOML format::

    [implications]
    "truck" = "land_vehicle"
    "car" = "land_vehicle"
    [aliases]
    "automobile" = "car"

There is support for a kind of descriptor implication
using a table called "descriptors".
This table does not create descriptor implications as described above,
but is a way of generating numerous regular implications
by multiplying strings in a way that would be tedious and error-prone
to do by hand.
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

The motivating use case for this functionality is the same as for
the original implementation of descriptor implications.
When you have many tags that take the form "adjective_noun",
you would like to have the qualified tag imply the base noun tag,
for example, as in the original example,
implying "green_shirt" to "shirt".
The following example (in TOML format) illustrates that usage::

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

The advantage of the TagActions format is that,
without the original string-matching variety of descriptor implications,
the possible outputs of the implication process are finite.
Removals are not supported by TagActions as they were introduced mainly
to counteract the problems created by descriptor implications.
As a result, the rules created by a TagActions file can be validated
for logical consistency in three ways.

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
using the ``refresh`` command's ``--validate`` option.

Querying the table
------------------

The ``query`` command prints galleries that match a given set of
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

The "any tag field" can be modified by the ``--field`` option.
Field names in field specifiers can be abbreviated as long as
the abbreviation is unambiguous.

By default, galleries are printed as CSV rows with no extra formatting
(``--format=none``).
To print query results with each field as a wrapped column,
create a "field formats file".
The name of this file is passed to the "FieldFormats" configuration key.
The default name is ``tableformat.conf``.
This filename is relative to the ``.galleries`` sub-directory of
your collection (the same as all filenames in the configuration).
The field formats file should contain the name of field you wish to include
in the query results, one per line,
followed by these formatting parameters:

:Maximum width:
    (*required*) Wrap the contents of this field to a column no wider
    than <maximum width>.
    Note the resulting column width may be less than this maximum
    if the contents don't need it.
    The special value "REM" can be given here to indicate
    "use remaining space for this column".

:Foreground color:
    Color the text <foreground color>.
    Choices include:
    "black", "red", "green", "yellow", "blue", "magenta", "cyan", "white",
    "bright black", "grey", "bright red", "bright green", "bright yellow",
    "bright blue", "bright magenta", "bright cyan", "bright white",
    or "" for default color.

:Background color:
    Color the background <background color>.
    Choices are the same as for foreground color.

:Effect:
    Use the <effect> terminal text effect.
    Choices include:
    "bold", "faint", "dim", "italic", "underline", "reverse video",
    "invert", or "" for none.

Each argument is separated by whitespace.
Whitespace in arguments must be quoted.
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

Once the field formats file is set up, enable formatted output
by setting the value of the ``--format`` option
or the "Format" configuration key in the [query] section.
A value of "format" means always format.
A value of "auto" will format if it detects that standard output
is connected to a terminal (and not, for example, a pipe).

Analyzing tag relationships
---------------------------

The ``overlaps`` and ``freq`` commands are used for analyzing the
co-occurrence of different tags.
First, run ``galleries overlaps`` to generate an overlap table for
one or more tag fields
An overlap table contains the number of times two tags
co-occur in a gallery, i.e. overlap.
The overlap table is stored in JSON format.
Then, run ``galleries freq`` to print a list of tags that frequently
co-occur with a given tag or tags.

Global configuration
====================

Besides the collection configuration file, ``db.conf``,
``galleries`` can be configured on a per-user level using the
global configuration file.
This file will be searched for in the following places:

#. ``${GALLERIES_CONF}`` if it is set
#. ``${XDG_CONFIG_HOME}/galleries/config``
#. ``${HOME}/.config/galleries/config`` if ``$XDG_CONFIG_HOME`` is unset

In the [collections] section of the global configuration,
you can specify short names for your collections.
These short names, when passed to the ``--collection`` option,
will be expanded to their full path value.
They can even be abbreviated as long as the abbreviation is unambiguous.

In the [global] section, you can specify default arguments.
The argument to the "Default" key will be passed to the ``--collection``
option if you omit it.
Pass a Boolean value to the "Verbose" key to set the default verbosity
level.

In the [init] section, you can specify two ways to customize the
``init`` function.
The key "TemplateConf" can be used to specify
a default configuration file (``db.conf``) for new collections
instead of the one generated by the program.
The value should be a path to a file, which is copied into the new
collection directory.
The key "TemplateDir" can be used to specify an entire directory
(to be named ``.galleries``) to copy into the new collection.
These settings can be bypassed by the ``--bare`` option.
