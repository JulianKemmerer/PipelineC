#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""In-process regression tests for the iteration-ordinal loop-naming scheme
(PY_TO_LOGIC.py's _elab_for/_bind_const_target/_elab_unpack_assign, plus the
expression-callee branch of _elab_call) -- covers every previously-unworkable
loop shape this unlocks (tuple/dict/string/enumerate/zip iteration, a nested
tuple target, tuple-unpacking assignment, an indexed/expression call target)
and the FOR_<var>_ITER_<n>_ name-shape guarantee, plus its error paths
(set/frozenset rejection, starred targets, arity mismatch, a non-iterable
iter, a non-callable call target).

Each design is written to its own temp .py file and parsed directly via
PY_TO_LOGIC.PARSE_FILE (not through the pypelinec CLI) -- same in-process
pattern as global_wire_errors_test.py / pylist_value_context_error_test.py.
"""
import os
import re
import sys
import tempfile

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

import PY_TO_LOGIC

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")

_HEADER = """
import sys, os
sys.path.insert(0, {repo_root!r})
from pypeline import MAIN, hw_func, uint32_t

"""


def _parse(src, name):
    with tempfile.TemporaryDirectory(prefix="loop_iter_naming_test_") as tmpdir:
        path = os.path.join(tmpdir, name)
        with open(path, "w") as f:
            f.write(_HEADER.format(repo_root=os.path.abspath(REPO_ROOT)))
            f.write(src)
        return PY_TO_LOGIC.PARSE_FILE(path)


# Anything outside [A-Za-z0-9_] is illegal in a VHDL basic identifier; instance
# names carry a legal "[<loc_str>]" call-site suffix, so that part is exempt.
_ILLEGAL_CHARS_RE = re.compile(r"[^A-Za-z0-9_\[\]]")


def _all_names(ps):
    """Every submodule instance name and wire/alias name across every
    elaborated function -- the full set of strings the loop prefix can
    reach."""
    names = []
    for logic in ps.FuncLogicLookupTable.values():
        names.extend(logic.submodule_instances.keys())
        names.extend(logic.wires)
    return names


def _assert_legal_vhdl(names, label):
    for n in names:
        prefix_part = n.split("[")[0]
        assert _ILLEGAL_CHARS_RE.search(prefix_part) is None, (
            f"{label}: name contains an illegal-for-VHDL character: {n!r}"
        )


# ── positive cases ──────────────────────────────────────────────────────


def test_tuple_iteration_and_ordinal_naming():
    # A list of tuples as the loop iterable -- the old repr()-based scheme
    # could not legally name this (parens/commas/spaces in repr()).
    src = """
OPS = [(0, 4, 2, 6), (1, 5, 3, 7), (2, 6, 4, 8)]

@MAIN
def m1(x: uint32_t) -> uint32_t:
    acc: uint32_t = x
    for op in OPS:
        acc = acc + op[0] + op[1] + op[2] + op[3]
    return acc
"""
    ps = _parse(src, "tuple_iter_test.py")
    names = _all_names(ps)
    assert any("FOR_op_ITER_0_" in n for n in names), (
        f"expected an ordinal-0 name under the tuple-iteration loop, found "
        f"none in: {sorted(names)[:10]}"
    )
    assert any("FOR_op_ITER_2_" in n for n in names), (
        "expected an ordinal-2 (last) name, found none"
    )
    _assert_legal_vhdl(names, "tuple_iter_test.py")
    print("test_tuple_iteration_and_ordinal_naming PASS")


def test_tuple_target_unpack_in_for():
    src = """
OPS = [(0, 4, 2, 6), (1, 5, 3, 7)]

@MAIN
def m1(x: uint32_t) -> uint32_t:
    acc: uint32_t = x
    for kind, a, b, c in OPS:
        acc = acc + kind + a + b + c
    return acc
"""
    ps = _parse(src, "tuple_target_test.py")
    names = _all_names(ps)
    assert any("FOR_kind_a_b_c_ITER_0_" in n for n in names), (
        f"expected a tuple-target prefix naming every leaf, found none in: "
        f"{sorted(names)[:10]}"
    )
    _assert_legal_vhdl(names, "tuple_target_test.py")
    print("test_tuple_target_unpack_in_for PASS")


def test_enumerate_zip_dict_str_iteration():
    # None of these were legal for-loop iterables before this change
    # (isinstance(iter_val, (range, tuple, list)) rejected all four).
    src = """
XS = [10, 20, 30]
YS = [1, 2, 3]
D = {"a": 1, "b": 2}

@MAIN
def m1(x: uint32_t) -> uint32_t:
    acc: uint32_t = x
    for i, v in enumerate(XS):
        acc = acc + i + v
    for a, b in zip(XS, YS):
        acc = acc + a + b
    for k in D:
        acc = acc + D[k]
    for c in "ab":
        acc = acc + 1
    return acc
"""
    ps = _parse(src, "iterables_test.py")
    assert ps is not None
    print("test_enumerate_zip_dict_str_iteration PASS")


def test_duplicate_iter_values_stay_distinct():
    # [1, 1, 2]: the OLD value-based scheme collided the first two
    # iterations onto one alias name (silently -- _add_wire has no
    # duplicate guard). The new ordinal scheme must keep all three distinct.
    src = """
VALS = [1, 1, 2]

@MAIN
def m1(x: uint32_t) -> uint32_t:
    acc: uint32_t = x
    for v in VALS:
        acc = acc + v
    return acc
"""
    ps = _parse(src, "dup_values_test.py")
    names = _all_names(ps)
    for want in ("FOR_v_ITER_0_", "FOR_v_ITER_1_", "FOR_v_ITER_2_"):
        assert any(want in n for n in names), (
            f"expected a distinct name for {want}, found none in: "
            f"{sorted(names)[:10]}"
        )
    print("test_duplicate_iter_values_stay_distinct PASS")


def test_negative_and_nested_values_legal_vhdl():
    # A negative int (old scheme: "FOR_i_-2_" -> WIRE_TO_VHDL_NAME's '-'->'_'
    # collapse gives the illegal "FOR_i__2_") and a nested tuple-valued loop,
    # both under a nested for -- must stay legal VHDL and accumulate
    # outermost-first.
    src = """
@MAIN
def m1(x: uint32_t) -> uint32_t:
    acc: uint32_t = x
    for i in range(-2, 1):
        for j in [(3, 4), (5, 6)]:
            acc = acc + j[0] + j[1]
    return acc
"""
    ps = _parse(src, "negative_nested_test.py")
    names = _all_names(ps)
    assert names, "expected at least one instance/alias name"
    _assert_legal_vhdl(names, "negative_nested_test.py")
    assert any("FOR_i_ITER_0_FOR_j_ITER_0_" in n for n in names), (
        f"expected nested prefixes to accumulate outermost-first, found "
        f"none in: {sorted(names)[:10]}"
    )
    print("test_negative_and_nested_values_legal_vhdl PASS")


def test_swap_unpack_assign():
    # a, b = b, a -- Case B (hardware-valued RHS) of _elab_unpack_assign.
    src = """
@MAIN
def m1(x: uint32_t, y: uint32_t) -> uint32_t:
    a: uint32_t = x
    b: uint32_t = y
    a, b = b, a
    return a - b
"""
    ps = _parse(src, "swap_unpack_test.py")
    assert ps is not None
    print("test_swap_unpack_assign PASS")


def test_const_unpack_assign():
    # op, pa, pb = PLAN[m] -- Case A (fully compile-time-constant RHS), the
    # soft_div.py shape this change was written to unblock.
    src = """
PLAN = {2: (1, 5, 7), 3: (2, 9, 11)}

@MAIN
def m1(x: uint32_t) -> uint32_t:
    acc: uint32_t = x
    for m in range(2, 4):
        op, pa, pb = PLAN[m]
        acc = acc + op + pa + pb
    return acc
"""
    ps = _parse(src, "const_unpack_test.py")
    assert ps is not None
    print("test_const_unpack_assign PASS")


def test_indexed_call_target():
    # LEAF_FNS[j](acc) -- an expression callee resolving, at elaboration
    # time, to a live hw_func closure. soft_cmp.py/soft_mult.py used to
    # document this as unsupported ("'Subscript' object has no attribute
    # 'id'").
    src = """
def make_leaf(k: int):
    @hw_func
    def leaf(v: uint32_t) -> uint32_t:
        return v + k
    return leaf

LEAF_FNS = [make_leaf(1), make_leaf(2), make_leaf(3)]

@MAIN
def m1(x: uint32_t) -> uint32_t:
    acc: uint32_t = x
    for j in range(3):
        acc = LEAF_FNS[j](acc)
    return acc
"""
    ps = _parse(src, "indexed_call_test.py")
    assert ps is not None
    print("test_indexed_call_target PASS")


def test_determinism_across_two_parses():
    # AUTOPIPELINE's pin-and-confirm loop re-parses in-process and matches
    # entities by name across passes -- names must be a pure function of
    # the design source (double_parse_file_test.py's own contract).
    src = """
OPS = [(0, 4, 2, 6), (1, 5, 3, 7), (2, 6, 4, 8)]

@MAIN
def m1(x: uint32_t) -> uint32_t:
    acc: uint32_t = x
    for op in OPS:
        acc = acc + op[0] + op[1] + op[2] + op[3]
    return acc
"""
    with tempfile.TemporaryDirectory(prefix="loop_iter_naming_determinism_") as tmpdir:
        path = os.path.join(tmpdir, "determinism_test.py")
        with open(path, "w") as f:
            f.write(_HEADER.format(repo_root=os.path.abspath(REPO_ROOT)))
            f.write(src)
        names1 = sorted(_all_names(PY_TO_LOGIC.PARSE_FILE(path)))
        names2 = sorted(_all_names(PY_TO_LOGIC.PARSE_FILE(path)))
    assert names1 == names2, (
        "instance/alias names changed across two PARSE_FILE calls on the "
        "same source -- naming must be a pure function of the design"
    )
    print("test_determinism_across_two_parses PASS")


# ── error paths ──────────────────────────────────────────────────────────


def _expect_elaboration_error(src, name, must_contain=()):
    try:
        _parse(src, name)
    except PY_TO_LOGIC.ElaborationError as e:
        msg = str(e)
        for token in must_contain:
            assert token.lower() in msg.lower(), (
                f"{name}: expected ElaborationError message to mention "
                f"{token!r}, got: {msg}"
            )
        print(f"{name} PASS  ({msg})")
        return
    raise AssertionError(
        f"{name}: expected an ElaborationError, but PARSE_FILE succeeded"
    )


def test_set_iteration_rejected():
    # Set iteration order is PYTHONHASHSEED-dependent -- not a deterministic
    # function of the design source -- so it must be rejected, not silently
    # accepted with whatever order this process happens to produce.
    src = """
@MAIN
def m1(x: uint32_t) -> uint32_t:
    acc: uint32_t = x
    for v in {1, 2, 3}:
        acc = acc + v
    return acc
"""
    _expect_elaboration_error(src, "set_iter_test.py", ["set", "frozenset"])


def test_starred_target_rejected():
    src = """
@MAIN
def m1(x: uint32_t) -> uint32_t:
    acc: uint32_t = x
    for a, *rest in [(1, 2, 3)]:
        acc = acc + a
    return acc
"""
    try:
        _parse(src, "starred_target_test.py")
    except NotImplementedError as e:
        assert "starred" in str(e).lower(), (
            f"expected a message naming starred targets, got: {e}"
        )
        print(f"starred_target_test.py PASS  ({e})")
        return
    raise AssertionError(
        "starred_target_test.py: expected NotImplementedError, but "
        "PARSE_FILE succeeded"
    )


def test_unpack_arity_mismatch_rejected():
    src = """
@MAIN
def m1(x: uint32_t) -> uint32_t:
    acc: uint32_t = x
    a, b, c = (1, 2)
    return acc + a + b + c
"""
    _expect_elaboration_error(src, "arity_mismatch_test.py", ["unpack"])


def test_for_iter_non_iterable_rejected():
    src = """
@MAIN
def m1(x: uint32_t) -> uint32_t:
    acc: uint32_t = x
    for v in 5:
        acc = acc + v
    return acc
"""
    _expect_elaboration_error(src, "non_iterable_test.py", ["iterable"])


def test_non_callable_expression_call_target_rejected():
    # NOT_CALLABLE[j] resolves (at elaboration time) to a plain int, not a
    # callable -- falls through _elab_call's expression-callee branch to the
    # same NotImplementedError a genuinely unsupported callee shape always
    # raised, not a new/different failure mode.
    src = """
NOT_CALLABLE = [1, 2, 3]

@MAIN
def m1(x: uint32_t) -> uint32_t:
    acc: uint32_t = x
    for j in range(3):
        acc = NOT_CALLABLE[j](acc)
    return acc
"""
    try:
        _parse(src, "not_callable_test.py")
    except NotImplementedError as e:
        assert "unsupported call form" in str(e).lower(), (
            f"expected a message naming the unsupported call form, got: {e}"
        )
        print(f"not_callable_test.py PASS  ({e})")
        return
    raise AssertionError(
        "not_callable_test.py: expected NotImplementedError, but PARSE_FILE "
        "succeeded"
    )


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
