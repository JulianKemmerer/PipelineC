#!/usr/bin/env python3
"""Generated VHDL doesn't change between parse passes of one run.

One pypelinec run re-parses several times (ex. AUTO_FSM schedule passes).
Every synthesized leaf hashes its VHDL inputs, so a file that differs between
passes invalidates cached leaf results, even on a warm rerun.

- c_structs_pkg: a later pass can use types an earlier pass didn't (a new
  FSM's operand mux needs uint8_t[2]). The package used to be rewritten with
  each pass's own type set. These tests drive
  VHDL._WRITE_GROW_ONLY_C_STRUCTS_PACKAGE directly with hand-built per-type
  chunks: a pass with no new types rewrites nothing, new types are appended,
  and a redefined type starts the package over.
- Source comments: a shared C built-in operator entity used to name the call
  site its pass happened to elaborate first.
- Identical re-renders: SYN's thread pool re-renders entity files other
  threads are reading; open(path, "w") truncated them even when the text was
  unchanged.

warm_copy_no_resynth_test (build_report) checks the end-to-end result.
"""


import os
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

import C_TO_LOGIC  # noqa: F401  (import order: VHDL's import chain)
import SYN
import VHDL


PREFIX = "package c_structs_pkg is\n-- fixed preamble\n"
PREFIX_BODY = "-- fixed preamble body\n"
# No pypeline_emission_names: RENDER_TEXT leaves text unchanged.
PARSER_STATE = SimpleNamespace()


def _decl(name, version=1):
    return f"  type {name} is record -- v{version}\n  end record;\n"


def _body(name, version=1):
    return f"  function {name}_to_slv -- v{version}\n"


def _write(out_dir, types, prefix=PREFIX):
    """One pass: types is [(name, version), ...] in dependency order."""
    text = prefix
    body = PREFIX_BODY
    marks = []
    for name, version in types:
        marks.append((name, len(text), len(body)))
        text += _decl(name, version)
        body += _body(name, version)
    SYN.SYN_OUTPUT_DIRECTORY = out_dir
    VHDL._WRITE_GROW_ONLY_C_STRUCTS_PACKAGE(text, body, marks, PARSER_STATE)
    with open(os.path.join(out_dir, "c_structs_pkg.pkg.vhd")) as f:
        return f.read()


def _expected(types, prefix=PREFIX):
    return (
        prefix
        + "".join(_decl(n, v) for n, v in types)
        + "\nend c_structs_pkg;\n"
        + "package body c_structs_pkg is\n"
        + PREFIX_BODY
        + "".join(_body(n, v) for n, v in types)
        + "end package body c_structs_pkg;\n"
    )


def _mtime_ns(out_dir):
    return os.stat(os.path.join(out_dir, "c_structs_pkg.pkg.vhd")).st_mtime_ns


def test_first_write_matches_single_pass_layout():
    with tempfile.TemporaryDirectory(prefix="c_structs_pkg_first_") as out_dir:
        types = [("a_t", 1), ("b_t", 1)]
        assert _write(out_dir, types) == _expected(types)


def test_later_pass_types_are_appended_and_kept():
    with tempfile.TemporaryDirectory(prefix="c_structs_pkg_grow_") as out_dir:
        _write(out_dir, [("a_t", 1), ("b_t", 1)])
        # A later pass drops b_t and needs a new type, listed before a_t in
        # its own order. Existing chunks keep their order; the new one is
        # appended; the unused b_t stays.
        grown = _write(out_dir, [("uint8_t[2]", 1), ("a_t", 1)])
        assert grown == _expected([("a_t", 1), ("b_t", 1), ("uint8_t[2]", 1)])


def test_pass_with_no_new_types_leaves_file_untouched():
    with tempfile.TemporaryDirectory(prefix="c_structs_pkg_same_") as out_dir:
        full = _write(out_dir, [("a_t", 1), ("b_t", 1), ("c_t", 1)])
        before = _mtime_ns(out_dir)
        # The warm-rerun case: an early pass with a subset of the types.
        assert _write(out_dir, [("a_t", 1), ("c_t", 1)]) == full
        assert _write(out_dir, [("b_t", 1)]) == full
        assert _mtime_ns(out_dir) == before, "unchanged package was rewritten"


def test_redefined_type_starts_over():
    with tempfile.TemporaryDirectory(prefix="c_structs_pkg_redef_") as out_dir:
        _write(out_dir, [("a_t", 1), ("b_t", 1)])
        types = [("a_t", 2), ("c_t", 1)]
        assert _write(out_dir, types) == _expected(types)


def test_changed_preamble_starts_over():
    with tempfile.TemporaryDirectory(prefix="c_structs_pkg_prefix_") as out_dir:
        _write(out_dir, [("a_t", 1), ("b_t", 1)])
        prefix = PREFIX + "-- new preamble line\n"
        types = [("a_t", 1)]
        assert _write(out_dir, types, prefix) == _expected(types, prefix)


def test_missing_package_file_ignores_stale_chunk_list():
    with tempfile.TemporaryDirectory(prefix="c_structs_pkg_missing_") as out_dir:
        _write(out_dir, [("a_t", 1), ("b_t", 1)])
        os.unlink(os.path.join(out_dir, "c_structs_pkg.pkg.vhd"))
        types = [("c_t", 1)]
        assert _write(out_dir, types) == _expected(types)


def test_identical_rerender_does_not_rewrite_the_file():
    # SYN's thread pool re-renders entity files other threads are reading.
    # A byte-identical re-render must not truncate the file (a reader saw it
    # empty and recorded the empty-file hash as a synthesis input).
    with tempfile.TemporaryDirectory(prefix="generated_vhdl_rewrite_") as out_dir:
        path = os.path.join(out_dir, "leaf_0CLK_12345678.vhd")
        VHDL.WRITE_TEXT_IF_CHANGED(path, "entity leaf is\nend;\n")
        os.utime(path, ns=(1, 1))
        VHDL.WRITE_TEXT_IF_CHANGED(path, "entity leaf is\nend;\n")
        assert os.stat(path).st_mtime_ns == 1, "identical text was rewritten"
        VHDL.WRITE_TEXT_IF_CHANGED(path, "entity leaf is\n-- changed\nend;\n")
        assert os.stat(path).st_mtime_ns != 1
        with open(path) as f:
            assert f.read() == "entity leaf is\n-- changed\nend;\n"


def test_builtin_operator_entities_have_no_call_site_comment():
    import AST as pypeline_ast

    def logic(func_name, is_c_built_in, line):
        l = C_TO_LOGIC.Logic()
        l.func_name = func_name
        l.is_c_built_in = is_c_built_in
        l.ast_meta = pypeline_ast.ASTMeta(
            src_file="/nowhere/design.py", line=line, col=0, end_col=None, raw=None
        )
        return l

    class NoDescriptions:
        def source_comment(self, raw):
            return ""

    parser_state = SimpleNamespace(
        pypeline_emission_names=NoDescriptions(),
        FuncLogicLookupTable={
            "BIN_OP_AND_uint1_t_uint1_t": logic("BIN_OP_AND_uint1_t_uint1_t", True, 57),
            "my_func": logic("my_func", False, 12),
        },
    )
    # One entity for every call site: no single call site to name.
    assert VHDL.SOURCE_COMMENT("BIN_OP_AND_uint1_t_uint1_t", parser_state) == ""
    # A user function's own definition is stable across passes.
    assert VHDL.SOURCE_COMMENT("my_func", parser_state) == "-- Source: design.py:12\n"


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
