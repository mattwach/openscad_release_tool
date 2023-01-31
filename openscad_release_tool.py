#!/usr/bin/env python3
"""Creates a directory structure that can be zipped up and uploaded to
thingverse/etc.

There are two cases:

  1) Relative include: in this case, the file is copied along the same
  relative path in the output dir.  There is no need to change the file.
  2) include path: In this case, the file is copied within --lib_dirname.  The
  use/import in the original file is then changed to use this new relative lib
  dir.

This continues recursively.
"""

from typing import Any, Callable, List, Set, Tuple

import argparse

import glob
import logging
import os
import shutil
import sys

PARSER = argparse.ArgumentParser(
    description='Bundle an OpenSCAD file and all of its includes into a single '
    'directory.')

PARSER.add_argument(
    'filename',
    help='Path to main OpenSCAD file.'
)

PARSER.add_argument(
    'output_dir',
    help='Where to place the output.  Directory must not yet exist unless '
    '--overwrite is used.'
)

PARSER.add_argument(
    '--lib_dirname',
    default='lib',
    help='Subdirectory within output_dir where library files are copied.'
)

PARSER.add_argument(
    '--overwrite',
    default=False,
    action='store_true',
    help='If true and output directory exists, recursively deletes/recreates '
    'output dir [careful!]')

PARSER.add_argument(
    '--clear_include_paths',
    default=False,
    action='store_true',
    help='If true, do not use any default include paths')

PARSER.add_argument(
    '--include_path',
    action='append',
    help='Add an include path.  Can be specified multiple times')

PARSER.add_argument(
    '--add',
    action='append',
    help='Adds a glob pattern. Any files matching this pattern will be copied '
    'from file <filename> tree to the <output_dir> tree. This option can be '
    'specified multiple times.')

PARSER.add_argument(
    '--ignore_imports',
    default=False,
    action='store_true',
    help='If true, do not try and parse import statements')

PARSER.add_argument(
    '--log',
    default='info',
    help='logging level: debug, info, warning, error')

ARGS = PARSER.parse_args()

INCLUDE_PATHS = []

if sys.platform == "darwin":
  INCLUDE_PATHS.append(
      os.path.join(os.path.expanduser("~"), 'Documents/OpenSCAD/libraries'))
elif sys.platform == "win32":
  INCLUDE_PATHS.append(
      os.path.join(os.path.expanduser("~"), r'My Documents\OpenSCAD\libraries'))
else:
  INCLUDE_PATHS.append(
      os.path.join(os.path.expanduser("~"), '.local/share/OpenSCAD/libraries'))

class Error(Exception):
  pass

class BadFileTypeError(Error):
  pass

class ImportNotFoundError(Error):
  pass

class InputFileNotFoundError(Error):
  pass

class IncludeNotFoundError(Error):
  pass

class InternalError(Error):
  pass

class LibDirExistsError(Error):
  pass

class OutputDirExistsError(Error):
  pass

def _prepare(
    filename: str, root_output_dir: str, lib_dirname: str, overwrite: bool
    ) -> None:
  """Checks and prepares environment, makes output dir.

  Args:
    filename: root filename that was provided at the commandline.
    root_output_dir: root output directory that was provided at the commandline.
    lib_dirname: The directory where library files should be copied.  Optionally
      provided at the commandline as --lib_dirname.
    overwrite: The value of --overwrite at the commandline.  If true, any
      existing root_output_dir will be wiped (as opposed to throwing an error).
  """
  if not os.path.exists(filename):
    raise InputFileNotFoundError('Could not find input file: %s' % filename)

  if os.path.isdir(filename):
    raise BadFileTypeError('Input file is a directory: %s' % filename)

  if os.path.exists(os.path.join(os.path.dirname(filename), lib_dirname)):
    raise LibDirExistsError(
        'The library output directory (%s) already exists in the source '
        'project. Please choose a different name using the --lib_dirname '
        'flag.' % lib_dirname)

  if os.path.exists(root_output_dir):
    if not overwrite:
      raise OutputDirExistsError(
          'Output directory already exists: %s  You can add --overwrite to '
          'automatically delete it.' % root_output_dir)
    logging.warning(
        'Deleting existing %s due to --overwrite', root_output_dir)
    shutil.rmtree(root_output_dir)

  logging.info('Creating %s', root_output_dir)
  os.makedirs(root_output_dir)

class CopyAndParse:
  """CopyAndParse is a per-character state machine parser.

    The parser mostly copies the file from source to destination.

    When a use or include is found, the associated include file is copied to
    the output directory, the include path in the source is modified if
    needed, and CopyAndParse is invokes recursively on the included file.

    This class also handles the import case.  The import case is similar to
    use/include except there is no need to recurse into the imported file.

    It's also possible for imports to be built up from variables or
    expressions.  This parser is not advanced enough to handle those
    cases and will output a warning when they are encountered.
  """
  # file_chars contains some substring of the currently parsed file,
  # it builds up automatically and is cleared by certain events.
  file_chars: List[str] = []
  # root_output_dir is the root of the output dir as provided at the commandline
  root_output_dir: str = ''
  # root_input_dir is the starting input directory which is sometimes
  # needed by imports
  root_input_dir: str = ''
  # Path to the target file
  target_path: str = ''
  # path to the source file
  source_path: str = ''
  # library output directory prefix, e.g. --lib_dirname
  lib_dirname: str = ''
  # Tracks a set of library paths that were used.  This is a shared structure
  # that is later used to search for license files.
  used_library_dirs = Set[str]
  # If true, imports are ignored by the parser.
  ignore_imports: bool = False

  def __init__(
      self,
      source_path: str,
      lib_dirname: str,
      root_input_dir: str,
      root_output_dir: str,
      target_path: str,
      indent: int,
      used_library_dirs: Set[str],
      ignore_imports: bool):
    self.source_path = source_path
    self.lib_dirname = lib_dirname
    self.root_output_dir = root_output_dir
    self.target_path = target_path
    self.indent = indent
    self.indent_str = '  ' * indent
    self.used_library_dirs = used_library_dirs
    self.used_library_dirs.add(os.path.abspath(os.path.dirname(source_path)))
    self.ignore_imports = ignore_imports

  def run(self) -> None:
    """Called to start parsing/copying."""
    if os.path.exists(self.target_path):
      logging.debug('%s%s already exists.', self.indent_str, self.target_path)
      return

    output_dir, _ = os.path.split(self.target_path)
    if not os.path.exists(output_dir):
      os.makedirs(output_dir)
    logging.info(
        '%scopy %s -> %s', self.indent_str, self.source_path, self.target_path)

    with open(self.source_path, 'r') as fin:
      file_data = fin.read()

    state = self._looking_for_word

    with open(self.target_path, 'w') as fout:
      for c in file_data:
        logging.debug(
            '%s%s->%s  (%s)',
            self.indent_str,
            self.source_path,
            c.replace('\n', '\\n'),
            state.__name__)
        self.file_chars.append(c)
        state = state(c, fout)

  def _looking_for_word(self, c: str, fout) -> Callable[[str], Any]:
    """State machine function: Looks for the start of a keyword token."""
    fout.write(c)
    if c in ('\n', ' ', '\t'):
      return self._looking_for_word
    self.file_chars = [c]
    return self._building_word

  def _building_word(self, c: str, fout) -> Callable[[str], Any]:
    """State machine function: builds up a word in self.file_chars."""
    fout.write(c)
    if c == '/' and self.file_chars[-2] == '/':
      # a line comment
      return self._looking_for_eol

    if c == '*' and self.file_chars[-2] == '/':
      # a block comment
      return self._looking_for_end_of_comment

    # The usual a-zA-Z0-9_ make up a "word".
    if (('A' <= c <= 'Z') or
        ('a' <= c <= 'z') or
        ('0' <= c <= '9') or
        (c == '_')):
      return self._building_word

    # Reached the end of the word, is it an interesting one?
    word = ''.join(self.file_chars[:-1])
    if word in ('include', 'use'):
      return self._looking_for_include(c, None)

    if word == 'import' and not self.ignore_imports:
      return self._looking_for_import(c, None)

    return self._looking_for_word

  def _looking_for_eol(self, c: str, fout) -> Callable[[str], Any]:
    """State machine function: searches for an end-of-line."""
    if fout:
      fout.write(c)
    if c != '\n':
      return self._looking_for_eol
    return self._looking_for_word

  def _looking_for_end_of_comment(self, c: str, fout) -> Callable[[str], Any]:
    """State machine function: searches for an end of a multi-line comment."""
    fout.write(c)
    if c == '/' and self.file_chars[-2] == '*':
      # end of block comment found
      return self._looking_for_word
    return self._looking_for_end_of_comment

  def _looking_for_semicolon(self, c: str, fout) -> Callable[[str], Any]:
    """State machine function: searches for a ;"""
    if fout:
      fout.write(c)
    if c != ';':
      return self._looking_for_semicolon
    return self._looking_for_word

  def _looking_for_import(self, c: str, fout) -> Callable[[str], Any]:
    """State machine function: Looks for the start of an import filename."""
    if fout:
      fout.write(c)

    if c == ')':
      logging.warning(
          '%sCould not resolve "%s" in %s',
          self.indent_str, ''.join(self.file_chars), self.source_path)
      return self._looking_for_word

    if c != '"':
      return self._looking_for_import

    word = ''.join(self.file_chars)
    word = ''.join(word.split(' \n\t'))
    if not word.endswith('("') and not word.endswith('file="'):
      return self._looking_for_import

    self.file_chars = []
    return self._build_import_path

  def _build_import_path(self, c: str, fout) -> Callable[[str], Any]:
    """State machine function: Builds an import path within self.file_chars."""
    if c != '"':
      return self._build_import_path

    import_path = ''.join(self.file_chars[:-1])
    new_import_path = import_path

    # three cases:
    # absolute path: need to make the path relative
    # relative path, can use as-is
    # relative-to-parent, also can use as-is

    if os.path.isabs(import_path):
      import_abs_path = import_path
      if new_import_path.startswith('/'):
        new_import_path = new_import_path[1:]
      if ':\\' in new_import_path:
        new_import_path = new_import_path[new_import_path.find(':\\') + 2:]
      new_import_path = os.path.join(self.lib_dirname, new_import_path)
    else:
      import_abs_path = os.path.join(
          os.path.dirname(self.source_path), import_path)

    if not os.path.exists(import_abs_path):
      import_abs_path = os.path.join(
          os.path.dirname(self.root_input_dir), import_path)

    if not os.path.exists(import_abs_path):
      raise ImportNotFoundError(
          'Could not find import path (%s) in %s' % (
            import_path, import_abs_path))

    target_path = os.path.join(self.root_output_dir, new_import_path)
    if not os.path.exists(os.path.dirname(target_path)):
      os.makedirs(os.path.dirname(target_path))
    if not os.path.exists(target_path):
      logging.info('%simport %s -> %s' ,
            self.indent_str, import_abs_path, target_path)
      shutil.copy(import_abs_path, target_path)

    fout.write(new_import_path)
    fout.write(c)

    return self._looking_for_semicolon

  def _looking_for_include(self, c: str, fout) -> Callable[[str], Any]:
    """State machine function: Looks for the start of an include path."""
    if fout:
      fout.write(c)
    if c in (' ', '\t', '\n'):
      return self._looking_for_include
    if c == '<':
      self.file_chars = []
      return self._building_include_path
    return self._looking_for_word

  def _building_include_path(self, c:str, fout) -> Callable[[str], Any]:
    """State machine function: Builds an include path within self.file_chars."""
    if c == '>':
      include_path = ''.join(self.file_chars[:-1])
      logging.debug('%sinclude path: %s', self.indent_str, include_path)
      source_path, target_path, new_include_path = self._find_included_file(
          include_path)
      fout.write(new_include_path)
      fout.write(c)
      CopyAndParse(
          source_path,
          self.lib_dirname,
          self.root_input_dir,
          self.root_output_dir,
          target_path,
          self.indent + 1,
          self.used_library_dirs,
          self.ignore_imports).run()
      return self._looking_for_word
    return self._building_include_path

  def _find_included_file(self, include_path: str) -> Tuple[str, str, str]:
    """Searches for an include path.

    Args:
      include_path: String as it would appear in a use/include statement

    Returns: (source_path, target_path, new_include_path), where source_path
      is the full path to the file, target_path is the full path to the
      destination (within the output_dir), and new_include_path is the
      new value for include path which may be equal to include_path or may not
      if the file is being copied from a library.
    """
    # check relative to the source dir
    source_dir, _ = os.path.split(self.source_path)
    output_dir, _ = os.path.split(self.target_path)
    if os.path.exists(os.path.join(source_dir, include_path)):
      # In this case, the path is relative to the source file.  We make the
      # file relative in the output_dir in the same way.  include_path
      # can stay the same.
      return (
        os.path.join(source_dir, include_path),
        os.path.join(output_dir, include_path),
        include_path)

    # Look though the provided include libraries.
    for include_prefix in INCLUDE_PATHS:
      if os.path.exists(os.path.join(include_prefix, include_path)):
        # the new output_path is the same as the OpenSCAD library path, but
        # now resides in the output directory, under --lib_name
        output_path = os.path.join(
            os.path.join(self.root_output_dir, self.lib_dirname),
            include_path)
        logging.debug('%soutput_dir: %s', self.indent_str, output_dir)
        logging.debug('%soutput_path: %s', self.indent_str, output_path)
        # calculate how to get from the output_dir of the target path to the
        # target file using relpath.  This handy Python built-in can avoid
        # messy-looking relative paths.
        rel_path = os.path.relpath(output_path, output_dir)
        logging.debug('%srel_path: %s', self.indent_str, rel_path)
        return (
            os.path.join(include_prefix, include_path),
            output_path,
            rel_path)

    raise IncludeNotFoundError('Could not find %s in %s or %s' %
        (include_path, output_dir, INCLUDE_PATHS))


def _find_license_files(
    project_dir: str,
    output_library_dir: str,
    used_library_dirs: Set[str]) -> None:
  """Searches for and copies license files.

  Args:
    project_dir: The directory where the root scad file lives.
    output_library_dir: Where library files are copied.
    used_library_dirs: A set of all of the library directories that provided files.
  """
  # License files are searched for up the directory tree.  stop_paths, indicates
  # Where the root of the libraries reside so that the search does not continue
  # all the way to the root directory (e.g. / in unix)
  stop_paths = set(os.path.abspath(p) for p in INCLUDE_PATHS)
  stop_paths.add(os.path.abspath(project_dir))
  already_copied = set()

  def contains_a_stop_path(library_dir):
    return any(p for p in stop_paths if library_dir.startswith(p))

  def copy_file(path):
    if path in already_copied:
      logging.debug('license file %s is already copied', path)
      return

    output_path = next(
        os.path.join(output_library_dir, path[len(p)+1:])
        for p in stop_paths if path.startswith(p))

    logging.info('License file %s -> %s', path, output_path)
    shutil.copy(path, output_path)
    already_copied.add(path)

  def find_files(library_dir):
    for name in ('COPYING', 'README'):
      if os.path.exists(os.path.join(library_dir, name)):
        copy_file(os.path.join(library_dir, name))
    for pattern in ('*.md', '*.MD', '*.txt', '*.TXT'):
      for path in glob.glob(os.path.join(library_dir, pattern)):
        copy_file(path)

  for library_dir in used_library_dirs:
    if not contains_a_stop_path(library_dir):
      logging.warning(
          'Can not look for license files in %s because there is no matching '
          'stop path prefix: %s', library_dir, stop_paths)
    else:
      while True:
        find_files(library_dir)
        if library_dir in stop_paths:
          break
        library_dir = os.path.dirname(library_dir)


def create_release_directory(
    pathname: str,
    root_output_dir: str,
    lib_dirname: str,
    overwrite: bool,
    ignore_imports: bool) -> None:
  """Main function to call if used as a library."""
  _prepare(pathname, root_output_dir, lib_dirname, overwrite)
  pathname = os.path.abspath(pathname)
  _, filename = os.path.split(pathname)
  used_library_dirs = set()

  CopyAndParse(
      os.path.abspath(pathname),
      lib_dirname,
      os.path.dirname(os.path.abspath(pathname)),
      root_output_dir,
      os.path.join(root_output_dir, filename),
      0,
      used_library_dirs,
      ignore_imports).run()

  _find_license_files(
      os.path.dirname(pathname),
      os.path.join(root_output_dir, lib_dirname),
      used_library_dirs)


def copy_add_files(
    source_dir: str,
    output_dir: str,
    glob_pattern: str):
  """Copies glob_patterns from the source to the destination directories."""
  for matching_file in glob.glob(
      os.path.join(os.path.join(source_dir, '**'), glob_pattern), recursive=True):
    if not matching_file.startswith(source_dir):
      raise InternalError('Expected %s to start with %s' % (matching_file, source_dir))
    relative_path = matching_file[len(source_dir) + 1:]
    output_path = os.path.join(output_dir, relative_path)
    if not os.path.exists(output_path):
      logging.info('Added file %s -> %s', matching_file, output_path)
      shutil.copy(matching_file, output_path)

def main():
  """Entry point."""
  numeric_level = getattr(logging, ARGS.log.upper(), None)
  if not isinstance(numeric_level, int):
    raise ValueError('Invalid log level: %s' % ARGS.log)
  logging.basicConfig(level=numeric_level, format='%(message)s')

  global INCLUDE_PATHS
  if ARGS.clear_include_paths:
    INCLUDE_PATHS = []

  if ARGS.include_path:
    INCLUDE_PATHS.extend(ARGS.include_path)

  try:
    create_release_directory(
        ARGS.filename,
        ARGS.output_dir,
        ARGS.lib_dirname,
        ARGS.overwrite,
        ARGS.ignore_imports)
    if ARGS.add:
      for glob_pattern in ARGS.add:
        copy_add_files(
            os.path.dirname(os.path.abspath(ARGS.filename)),
            ARGS.output_dir,
            glob_pattern)
    output_path = os.path.join(
        os.path.abspath(ARGS.output_dir), os.path.split(ARGS.filename)[1])
    print('\n*** SUCCESSFULLY WROTE %s and needed support files ***' % output_path)
    if sys.platform != 'win32':
      print('To view in OpenSCAD:')
      print('  openscad "%s"' % output_path)
      print('To zip for release:')
      parent_dir, zip_name = os.path.split(ARGS.output_dir)
      print('  pushd "%s" && zip -r "%s.zip" "%s"' %
          (parent_dir, zip_name, zip_name))
  except Error as e:
    sys.exit(e)

if __name__ == '__main__':
  main()
