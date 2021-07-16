help:
	@echo 'The Makefile is only used for testing.  If you would like to test, run make test'

test: lint integration

lint:
	pylint *.py

integration:
	./openscad_release_tool.py \
   --overwrite \
   --clear_include_paths \
   --include_path test/lib \
   --lib_dirname library \
   --add '*.add' \
   test/main/test.scad \
   /tmp/openscad_release_test
	diff -r /tmp/openscad_release_test test/expected
	@echo '*** Integration tests passed ***'


