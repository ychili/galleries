===========
 Galleries
===========

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
See Global Configuration section for how to set up short names
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

Implications, aliases, and removals
-----------------------------------

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
