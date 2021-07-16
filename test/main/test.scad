// This is a comment
// include <just_a_comment.scad>
// use <just_a_comment.scad>
include <dep1.scad>; use <dep2.scad>
include <nested/dep3.scad>
include <nested2/dep12.scad>

color("#fff") import("some_file.stl");
color("#ddd") import("stl/some_file2.stl");
use <dep4.scad>
