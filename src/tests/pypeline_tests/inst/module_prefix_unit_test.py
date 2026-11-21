#!/usr/bin/env python3
"""VHDL.NAMESPACE_VHDL_FILES and its helpers (--module_prefix), on hand-built
VHDL files: no design is built. module_prefix_build_test.py checks the whole
flow with GHDL and Yosys.
"""

import os
import sys
import tempfile

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

import SYN
import VHDL

PACKAGE = """library ieee;
use ieee.std_logic_1164.all;
package pkg_types is
  subtype word_t is std_logic_vector(7 downto 0);
end package;
package body pkg_types is
end package body;
"""

CHILD = """library ieee;
use ieee.std_logic_1164.all;
use work.pkg_types.all;
entity Child_0CLK_1234 is
  port (a : in word_t; y : out word_t);
end Child_0CLK_1234;
architecture arch of Child_0CLK_1234 is
begin
  y <= a; -- Child_0CLK_1234 passes a through
end arch;
"""

TOP = """library ieee;
use ieee.std_logic_1164.all;
use work.pkg_types.all;
entity top_core is
  port (a : in word_t; y : out word_t);
end top_core;
architecture arch of top_core is
begin
  -- Instantiates child_0clk_1234 (a different case spelling)
  u : entity work.child_0clk_1234 port map (a, y);
  assert false report "child_0clk_1234 stays in this string" severity note;
end arch;
"""


def make_files(directory, **texts):
    paths = []
    for name, text in texts.items():
        path = os.path.join(directory, name + ".vhd")
        with open(path, "w") as f:
            f.write(text)
        paths.append(path)
    return paths


def namespace(prefix="p_", top="top_core", **texts):
    """(new paths, source dir, destination dir) of NAMESPACE_VHDL_FILES on
    files made from texts, in a fresh temporary directory."""
    root = tempfile.mkdtemp(prefix="module_prefix_unit_")
    src = os.path.join(root, "src")
    os.makedirs(src)
    paths = make_files(src, **texts)
    dest = os.path.join(root, "top_core", "vhdl")
    return VHDL.NAMESPACE_VHDL_FILES(paths, prefix, top, dest), src, dest


def read(path):
    with open(path) as f:
        return f.read()


def test_declared_units_are_entities_and_packages_not_bodies():
    assert VHDL.GET_DECLARED_UNITS(PACKAGE) == [("package", "pkg_types")]
    assert VHDL.GET_DECLARED_UNITS(CHILD) == [("entity", "Child_0CLK_1234")]
    # A commented-out declaration is not one
    assert VHDL.GET_DECLARED_UNITS("-- entity ghost is\n") == []


def test_every_unit_and_reference_is_renamed_but_the_top():
    paths, _, dest = namespace(pkg=PACKAGE, child=CHILD, top_core=TOP)
    assert [os.path.basename(p) for p in paths] == [
        "p_pkg.vhd",
        "p_child.vhd",
        "top_core.vhd",
    ]
    assert sorted(os.listdir(dest)) == sorted(os.path.basename(p) for p in paths)
    pkg, child, top = (read(p) for p in paths)
    assert "package p_pkg_types is" in pkg and "package body p_pkg_types is" in pkg
    assert "use work.p_pkg_types.all;" in child
    assert "entity p_Child_0CLK_1234 is" in child
    assert "end p_Child_0CLK_1234;" in child
    assert "architecture arch of p_Child_0CLK_1234 is" in child
    assert "entity top_core is" in top and "end top_core;" in top
    assert "entity work.p_child_0clk_1234 port map" in top  # case as written


def test_comments_and_strings_are_untouched():
    paths, _, _ = namespace(pkg=PACKAGE, child=CHILD, top_core=TOP)
    child, top = read(paths[1]), read(paths[2])
    assert "-- Child_0CLK_1234 passes a through" in child
    assert "-- Instantiates child_0clk_1234 (a different case spelling)" in top
    assert '"child_0clk_1234 stays in this string"' in top


def test_writes_only_the_listed_files():
    root = tempfile.mkdtemp(prefix="module_prefix_unit_")
    src = os.path.join(root, "src")
    os.makedirs(src)
    paths = make_files(
        src,
        pkg=PACKAGE,
        top_core=TOP.replace("entity work.child_0clk_1234 port map (a, y)", "y <= a"),
    )
    dest = os.path.join(root, "vhdl")
    os.makedirs(dest)
    for stale in ("old_unit.vhd", "p_pkg.vhd.bak"):
        with open(os.path.join(dest, stale), "w") as f:
            f.write("stale")
    VHDL.NAMESPACE_VHDL_FILES(paths, "p_", "top_core", dest)
    assert sorted(os.listdir(dest)) == ["p_pkg.vhd", "top_core.vhd"]
    # The sources are left as they were
    assert read(paths[0]) == PACKAGE


def test_a_rename_onto_an_existing_name_is_refused():
    clash = (
        CHILD
        + "-- p_child_0clk_1234 is only a comment\nsignal p_Child_0CLK_1234 : bit;\n"
    )
    try:
        namespace(pkg=PACKAGE, child=clash, top_core=TOP)
    except Exception as e:
        assert "would rename" in str(e) and "p_" in str(e), e
    else:
        raise AssertionError("a name the design already uses was accepted")


def test_a_missing_top_is_refused():
    try:
        namespace(top="not_there", pkg=PACKAGE, child=CHILD)
    except Exception as e:
        assert "not_there" in str(e), e
    else:
        raise AssertionError("a file list without the top was accepted")


def test_two_files_with_one_name_are_refused():
    root = tempfile.mkdtemp(prefix="module_prefix_unit_")
    paths = []
    for sub in ("one", "two"):
        os.makedirs(os.path.join(root, sub))
        paths += make_files(
            os.path.join(root, sub), pkg=PACKAGE if sub == "one" else CHILD
        )
    paths += make_files(root, top_core=TOP)
    try:
        VHDL.NAMESPACE_VHDL_FILES(paths, "p_", "top_core", os.path.join(root, "vhdl"))
    except Exception as e:
        assert "share a file name" in str(e), e
    else:
        raise AssertionError("two files for one name were accepted")


def test_a_file_name_over_the_limit_is_refused():
    long_name = "e" * (VHDL.MAX_FILE_NAME_BYTES - len(".vhd") - 1)
    text = CHILD.replace("Child_0CLK_1234", long_name)
    try:
        namespace(
            pkg=PACKAGE,
            **{long_name: text},
            top_core=TOP.replace("child_0clk_1234", long_name),
        )
    except Exception as e:
        assert "longer" in str(e), e
    else:
        raise AssertionError("a file name over the limit was accepted")


def test_prefixes_that_cannot_start_an_identifier_are_refused():
    for good in ("a_", "enc_", "wg", "A1_b2_", "x"):
        assert VHDL.MODULE_PREFIX_ERROR(good) is None, good
    for bad in ("", "9x", "_a", "a__", "a__b_", "a-b", "a b", "é_"):
        assert VHDL.MODULE_PREFIX_ERROR(bad), bad
    try:
        namespace(
            prefix="a__",
            pkg=PACKAGE,
            top_core=TOP.replace(
                "entity work.child_0clk_1234 port map (a, y)", "y <= a"
            ),
        )
    except Exception as e:
        assert "VHDL identifier" in str(e), e
    else:
        raise AssertionError("a bad prefix was accepted")


def test_listed_paths_are_mapped_in_a_tcl_list():
    path_map = {"/o/a.vhd": "/o/top/vhdl/p_a.vhd", "/o/top.vhd": "/o/top/vhdl/top.vhd"}
    line = "read_vhdl -vhdl2008 -library work {/o/a.vhd /o/top.vhd /o/other.vhd }"
    assert SYN.MAP_LISTED_PATHS(line, path_map) == (
        "read_vhdl -vhdl2008 -library work "
        "{/o/top/vhdl/p_a.vhd /o/top/vhdl/top.vhd /o/other.vhd }"
    )
    assert SYN.MAP_LISTED_PATHS("set x /o/a.vhd.bak", path_map) == "set x /o/a.vhd.bak"


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
