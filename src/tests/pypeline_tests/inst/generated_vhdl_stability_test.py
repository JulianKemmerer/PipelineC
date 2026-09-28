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
- c_structs_pkg is merged by emitted VHDL type name, not logical C type. A
  factory struct sized by an AUTO_PIPELINE .latency (WireGuard's Poly1305
  powers_t, 2 lanes in pass 1 and 5 in pass 2) has a new logical key in
  each pass but the same emitted name. Merged by logical key, the package
  declared that name twice and Vivado rejected it (Synth 8-989). Real
  pypeline_names.EmissionNames render these chunks.
  c_structs_pkg_relayout_test covers the same case with a real parse.
- Source comments: a shared C built-in operator entity used to name the call
  site its pass happened to elaborate first.
- Identical re-renders: SYN's thread pool re-renders entity files other
  threads are reading; open(path, "w") truncated them even when the text was
  unchanged.

warm_copy_no_resynth_test (build_report) checks the end-to-end result.
"""


import json
import os
import re
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

import C_TO_LOGIC  # noqa: F401  (import order: VHDL's import chain)
import pypeline_names
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


def _write_chunks(out_dir, chunks, parser_state=PARSER_STATE, prefix=PREFIX):
    """One pass: chunks is [(declared name, decl text, body text), ...] in
    dependency order, with names as the pass's parser_state renders them."""
    text = prefix
    body = PREFIX_BODY
    marks = []
    for name, decl_text, body_text in chunks:
        marks.append((name, len(text), len(body)))
        text += decl_text
        body += body_text
    SYN.SYN_OUTPUT_DIRECTORY = out_dir
    VHDL._WRITE_GROW_ONLY_C_STRUCTS_PACKAGE(text, body, marks, parser_state)
    with open(os.path.join(out_dir, "c_structs_pkg.pkg.vhd")) as f:
        return f.read()


def _write(out_dir, types, prefix=PREFIX):
    """One pass: types is [(name, version), ...] in dependency order."""
    return _write_chunks(
        out_dir,
        [(name, _decl(name, version), _body(name, version)) for name, version in types],
        prefix=prefix,
    )


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
        grown = _write(out_dir, [("uint8_t_2", 1), ("a_t", 1)])
        assert grown == _expected([("a_t", 1), ("b_t", 1), ("uint8_t_2", 1)])


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


def _mac_pass(lanes_by_direction):
    """One parse pass of a make_mac(direction) factory, as chunks plus that
    pass's parser_state. Like WireGuard's Poly1305 MAC, powers_t.values is
    sized by a .latency-derived lane count, which is not a factory parameter.
    acc_t depends on powers_t. EmissionNames is built from this pass's types
    only, as each parse builds it."""
    descriptions = {}
    chunks = []
    for direction, lanes in sorted(lanes_by_direction.items()):
        array = f"uint32_t_{lanes}"
        powers = f"powers_t_values_uint32_t_{lanes}_direction_{direction}"
        acc = f"acc_t_powers_{powers}_valid_uint1_t_direction_{direction}"
        for raw, symbol in ((powers, "powers_t"), (acc, "acc_t")):
            descriptions[raw] = {
                pypeline_names.NameInfo(
                    "struct",
                    symbol,
                    "mac",
                    f"make_mac.<locals>.{symbol}",
                    "/nowhere/mac.py",
                    10,
                    params=(("direction", direction),),
                    identity=raw,
                )
            }
        if array not in [c[0] for c in chunks]:
            chunks.append(
                (
                    array,
                    f"  type {array} is array(0 to {lanes - 1}) of uint32_t;\n",
                    f"  function {array}_to_slv\n",
                )
            )
        chunks.append(
            (
                powers,
                f"  type {powers} is record\n    values : {array};\n  end record;\n",
                f"  function {powers}_to_slv -- {array}_SLV_LEN\n",
            )
        )
        chunks.append(
            (
                acc,
                f"  type {acc} is record\n    powers : {powers};\n"
                "    valid : uint1_t;\n  end record;\n",
                f"  function {acc}_to_slv\n",
            )
        )
    names = pypeline_names.EmissionNames(descriptions)
    return chunks, SimpleNamespace(pypeline_emission_names=names)


def _emitted(mac_pass, raw):
    return mac_pass[1].pypeline_emission_names.identifier(raw)


def _assert_each_type_declared_once(package):
    declared = [
        name.lower()
        for name in re.findall(r"(?im)^\s*(?:type|subtype)\s+(\w+)\s+is\b", package)
    ]
    duplicates = sorted({n for n in declared if declared.count(n) > 1})
    assert not duplicates, f"VHDL types declared more than once: {duplicates}"


def test_relayout_under_one_vhdl_name_starts_over():
    # WireGuard's shared build: pass 1 elaborated 2 lanes per direction, pass
    # 2 resized encrypt to 5 and decrypt to 7. Each pass's EmissionNames saw
    # one powers_t per direction, so both passes emit the same name.
    pass1 = _mac_pass({"encrypt": 2, "decrypt": 2})
    pass2 = _mac_pass({"encrypt": 5, "decrypt": 7})
    for direction, lanes in (("encrypt", 5), ("decrypt", 7)):
        assert _emitted(
            pass1, f"powers_t_values_uint32_t_2_direction_{direction}"
        ) == _emitted(
            pass2, f"powers_t_values_uint32_t_{lanes}_direction_{direction}"
        ), "fixture no longer reproduces the cross-pass name reuse"
    with tempfile.TemporaryDirectory(prefix="c_structs_pkg_relayout_") as out_dir:
        with tempfile.TemporaryDirectory(prefix="c_structs_pkg_fresh_") as fresh_dir:
            _write_chunks(out_dir, *pass1)
            package = _write_chunks(out_dir, *pass2)
            _assert_each_type_declared_once(package)
            # Only pass 2's layouts: the old ones would redeclare their names.
            assert package == _write_chunks(fresh_dir, *pass2)
            assert "array(0 to 4)" in package and "array(0 to 6)" in package
            assert "array(0 to 1)" not in package


def test_repeated_relayout_passes_settle():
    with tempfile.TemporaryDirectory(prefix="c_structs_pkg_settle_") as out_dir:
        with tempfile.TemporaryDirectory(prefix="c_structs_pkg_fresh_") as fresh_dir:
            _write_chunks(out_dir, *_mac_pass({"encrypt": 2}))
            resized = _write_chunks(out_dir, *_mac_pass({"encrypt": 5}))
            before = _mtime_ns(out_dir)
            # A confirmation pass with the same latencies changes nothing.
            assert _write_chunks(out_dir, *_mac_pass({"encrypt": 5})) == resized
            assert _mtime_ns(out_dir) == before, "unchanged package was rewritten"
            # A layout that flips back restarts the package again (the
            # documented cost: its leaves are re-synthesized, not reused).
            flipped = _write_chunks(out_dir, *_mac_pass({"encrypt": 2}))
            assert flipped == _write_chunks(fresh_dir, *_mac_pass({"encrypt": 2}))


def test_same_declaration_from_another_logical_type_is_kept():
    def one_pass(raw):
        info = pypeline_names.NameInfo(
            "struct", "flags_t", "mac", "make_mac.<locals>.flags_t", "/nowhere/mac.py", 3,
            params=(("direction", "encrypt"),), identity=raw,
        )
        names = pypeline_names.EmissionNames({raw: {info}})
        chunks = [
            (
                raw,
                f"  type {raw} is record\n    ok : uint1_t;\n  end record;\n",
                f"  function {raw}_to_slv\n",
            )
        ]
        return chunks, SimpleNamespace(pypeline_emission_names=names)

    with tempfile.TemporaryDirectory(prefix="c_structs_pkg_samedecl_") as out_dir:
        first = _write_chunks(out_dir, *one_pass("flags_t_ok_uint1_t_lanes_2"))
        before = _mtime_ns(out_dir)
        # A new logical key whose rendered declaration is byte-identical is
        # the same VHDL type: nothing to rewrite, cached leaves stay valid.
        assert _write_chunks(out_dir, *one_pass("flags_t_ok_uint1_t_lanes_5")) == first
        assert _mtime_ns(out_dir) == before, "identical declaration rewrote the package"


def test_vhdl_type_names_are_case_insensitive():
    with tempfile.TemporaryDirectory(prefix="c_structs_pkg_case_") as out_dir:
        _write(out_dir, [("Foo_t", 1)])
        # foo_T is Foo_t to a VHDL tool; appending it would redeclare it.
        types = [("foo_T", 2)]
        assert _write(out_dir, types) == _expected(types)


def test_pre_format_index_starts_over():
    # An output directory from before the index was keyed by VHDL name (the
    # WireGuard failure): same preamble, chunks keyed by logical type, and a
    # package that declares one VHDL name twice. It must not be merged.
    with tempfile.TemporaryDirectory(prefix="c_structs_pkg_legacy_") as out_dir:
        legacy = [["p_lanes_2", _decl("p_t", 1), _body("p_t", 1)],
                  ["p_lanes_5", _decl("p_t", 2), _body("p_t", 2)]]
        with open(os.path.join(out_dir, VHDL.C_STRUCTS_PKG_CHUNKS_FILE), "w") as f:
            json.dump({"prefix": [PREFIX, PREFIX_BODY], "chunks": legacy}, f)
        with open(os.path.join(out_dir, "c_structs_pkg.pkg.vhd"), "w") as f:
            f.write(_expected([("p_t", 1), ("p_t", 2)]))
        types = [("p_t", 2)]
        package = _write(out_dir, types)
        assert package == _expected(types)
        _assert_each_type_declared_once(package)
        with open(os.path.join(out_dir, VHDL.C_STRUCTS_PKG_CHUNKS_FILE)) as f:
            assert json.load(f)["format"] == VHDL.C_STRUCTS_PKG_CHUNKS_FORMAT


def test_one_pass_declaring_a_vhdl_name_twice_is_an_error():
    with tempfile.TemporaryDirectory(prefix="c_structs_pkg_dup_") as out_dir:
        try:
            _write(out_dir, [("Foo_t", 1), ("foo_t", 1)])
        except Exception as e:
            assert "both declare VHDL type" in str(e), e
        else:
            raise AssertionError("two declarations of one VHDL name were written")


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
