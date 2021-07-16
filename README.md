# Overview

`openscad_release_tool` bundles your OpenSCAD design along with any library
dependencies it uses into a single output directory.  This directory can then be
zipped up and loaded to Thingverse/cult3d/etc.

Anyone who downloads this uploaded zip file can then load your model into
OpenSCAD without having to install the libraries you used.

This is great for people who are not (yet) OpenSCAD users but want to make
parameter changes to a model without the friction of tracking down and
installing libraries.

# Usage Example

Say you want to upload `my_model.scad` to Thingverse but `my_model.scad` is
making use of a bunch of installed dependencies that are local to your machine.
To create a release:

    ./openscad_release_tool.py my_model.scad /tmp/my_model
    cd /tmp
    zip -r my_model.zip my_model

Now you can upload `my_model.zip` to Thingverse.  Someone who downloads
`my_model.zip` can then load it into OpenSCAD with no extra steps needed.

**Note:** Always load the generated output into OpenSCAD to verify it can load
without any problems.  Even better, load it onto a machine (or account) that
does not have the needed libraries installed as these might make a broken
release directory work anyway.

# Library License Files

This program makes an effort to include license files (e.g. `COPYING`, `*.md`,
etc.) of included libraries but it's possible that it might miss some.  It
would be prudent to verify that the output directory contains these files.

# Import Limitations

The parser is not as advanced as the OpenSCAD one.  In particular, something
like `import(some_variable)` can be handled by real OpenSCAD but is not
resolvable by this parser.

For these cases, you can use the `--add` flag to add your dependencies as a
separate step.  For example:


    ./openscad_release_tool.py --add '*.stl' --add '*.svg' /somedir/my_model.scad /tmp/my_model

In the example above, all of the `.stl` and `.svg` files found in `/somedir` or a
nested directory will be copied to `/tmp/my_model/`.

If imports are confusing the parser and preventing the process from completing,
you can add the `--ignore_imports` flag.  Adding it to the command above:

    ./openscad_release_tool.py --ignore_imports --add '*.stl' --add '*.svg' /somedir/my_model.scad /tmp/my_model

# Other Options

To see all options, run the command with with `--help` flag.


