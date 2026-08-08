import os
import sys
import tempfile

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

import PY_TO_LOGIC

# In-process regression tests for the global Wire[T]/Output[T] error paths
# introduced alongside multi-writer split-field driving: each design below is
# written to its own temp .py file and parsed directly via PY_TO_LOGIC.PARSE_FILE
# (not through the pypelinec CLI), since the check is "which ElaborationError is
# raised", mirroring pylist_value_context_error_test.py's in-process pattern.
# PARSE_FILE evicts its own per-parse caches/sys.modules on every call (see
# PY_TO_LOGIC.py's PARSE_FILE / the double_parse_file_test.py regression it
# guards), so no manual DEL_ALL_CACHES is needed between the designs below.

_HEADER = """
import sys, os
sys.path.insert(0, {repo_root!r})
from pypeline import MAIN, NamedTuple, Reg, Wire, struct, uint1_t, uint8_t

@struct
class point_t(NamedTuple):
    x: uint8_t
    y: uint8_t

"""

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")


def _parse(src, name):
    with tempfile.TemporaryDirectory(prefix="global_wire_errors_test_") as tmpdir:
        path = os.path.join(tmpdir, name)
        with open(path, "w") as f:
            f.write(_HEADER.format(repo_root=os.path.abspath(REPO_ROOT)))
            f.write(src)
        return PY_TO_LOGIC.PARSE_FILE(path)


def _expect_elaboration_error(src, name, must_contain):
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


def test_overlapping_leaf_from_two_writers():
    # Both writers claim .x -- must be rejected even though .y is untouched by
    # either (real conflict is on the same leaf, not "the whole wire").
    src = """
w: Wire[point_t]

@MAIN
def writer_a():
    w.x = 1

@MAIN
def writer_b():
    w.x = 2
"""
    _expect_elaboration_error(
        src, "overlapping_leaf_test.py", ["w", "writer_a", "writer_b"]
    )


def test_whole_write_plus_field_write_conflict():
    # One function drives the whole wire, another drives just .y -- the whole
    # write covers every field, so it conflicts with any other writer.
    src = """
w: Wire[point_t]

@MAIN
def writer_a():
    w = point_t(x=1, y=2)

@MAIN
def writer_b():
    w.y = 3
"""
    _expect_elaboration_error(
        src, "whole_plus_field_conflict_test.py", ["w", "writer_a", "writer_b"]
    )


def test_nested_leaf_overlap():
    # Overlap detection at NESTED depth: both writers touch w.a.x (two levels
    # down). Disjoint sibling leaves (w.a.y from writer_b) don't excuse it.
    src = """
@struct
class pair_t(NamedTuple):
    a: point_t
    b: point_t

w: Wire[pair_t]

@MAIN
def writer_a():
    w.a.x = 1
    w.b.y = 2

@MAIN
def writer_b():
    w.a.x = 3
    w.a.y = 4
"""
    _expect_elaboration_error(
        src, "nested_leaf_overlap_test.py", ["w", "writer_a", "writer_b"]
    )


def test_field_vs_enclosing_subtree_overlap():
    # A whole-subtree claim (writer_a writes ALL of w.a) conflicts with a
    # deeper claim inside that subtree from another writer (w.a.y) -- prefix
    # overlap at interior nodes, not just identical leaves.
    src = """
@struct
class pair_t(NamedTuple):
    a: point_t
    b: point_t

w: Wire[pair_t]

@MAIN
def writer_a():
    w.a = point_t(x=1, y=2)

@MAIN
def writer_b():
    w.a.y = 3
"""
    _expect_elaboration_error(
        src, "subtree_overlap_test.py", ["w", "writer_a", "writer_b"]
    )


def test_array_element_overlap():
    # Constant-index array claims that COLLIDE on element 1 must be rejected
    # (writer_a's unrolled range(2) covers [0],[1]; writer_b writes [1]).
    src = """
arr_w: Wire[uint8_t[4]]

@MAIN
def writer_a():
    for i in range(2):
        arr_w[i] = 1

@MAIN
def writer_b():
    arr_w[1] = 2
"""
    _expect_elaboration_error(
        src, "array_element_overlap_test.py", ["arr_w", "writer_a", "writer_b"]
    )


def test_dynamic_index_write_rejected_with_multiple_writers():
    # A genuinely runtime (non-unrolled) variable-index write to a global
    # array Wire[T] can't be safely combined with a second writer -- the
    # dynamic index isn't tracked in global_wire_driven_paths (only static
    # leaf paths are), so overlap can't be proven disjoint. This exercises
    # PY_TO_LOGIC.py's global_wire_dynamic_index_writes guard, set by
    # _emit_var_ref_assign and checked in the >1-writer validation.
    #
    # Previously unexercisable: `arr_w[i] = ...` on a global array wire (with
    # i a real runtime value, e.g. from a Reg) crashed
    # _build_var_ref_assign_logic with "VAR_REF_ASSIGN position count
    # mismatch" even with a SINGLE writer, before this guard's own code ever
    # ran -- see the elem_c_type fix in _emit_var_ref_assign (elem_c_type
    # must be the array's declared element type, not the RHS expression's
    # own elaborated type, so output_type and elem_c_type stay structurally
    # consistent for _get_elem_positions).
    src = """
arr_w: Wire[uint8_t[4]]

@MAIN
def writer_a():
    n: Reg[uint8_t]
    idx: uint8_t = n & 3
    arr_w[idx] = n
    n += 1

@MAIN
def writer_b():
    arr_w[0] = 2
"""
    _expect_elaboration_error(
        src, "dynamic_index_multi_writer_test.py", ["arr_w", "writer_a", "writer_b"]
    )


def test_dynamic_index_write_global_wire_positive_case():
    # Regression test for the VAR_REF_ASSIGN "position count mismatch" bug:
    # a genuinely runtime (non-unrolled) variable-index write to a global
    # array Wire[T], SINGLE writer, must elaborate cleanly. Pre-fix this
    # crashed unconditionally (before the multi-writer guard above could
    # ever even run) because _emit_var_ref_assign set elem_c_type from the
    # RHS's own elaborated type instead of the array's declared element
    # type.
    src = """
arr_w: Wire[uint8_t[4]]

@MAIN
def writer():
    n: Reg[uint8_t]
    idx: uint8_t = n & 3
    arr_w[idx] = 1
    n += 1
"""
    try:
        _parse(src, "dynamic_index_write_global_wire_test.py")
    except PY_TO_LOGIC.ElaborationError as e:
        raise AssertionError(
            f"dynamic_index_write_global_wire_test.py: expected clean "
            f"elaboration (single-writer runtime-index array write), got "
            f"ElaborationError: {e}"
        )
    print("dynamic_index_write_global_wire_test.py PASS (no error, as expected)")


def test_dynamic_index_write_local_var_positive_case():
    # Same bug, but on a LOCAL array variable rather than a global Wire[T] --
    # confirms the root cause (RHS-type vs LHS-declared-element-type
    # mismatch in _emit_var_ref_assign) is not global-wire-specific: it
    # reproduced identically for a local uint8_t[N] variable pre-fix.
    src = """
@MAIN
def writer():
    n: Reg[uint8_t]
    arr: uint8_t[4] = [0, 0, 0, 0]
    idx: uint8_t = n & 3
    arr[idx] = 1
    n += 1
"""
    try:
        _parse(src, "dynamic_index_write_local_var_test.py")
    except PY_TO_LOGIC.ElaborationError as e:
        raise AssertionError(
            f"dynamic_index_write_local_var_test.py: expected clean "
            f"elaboration (runtime-index local array write), got "
            f"ElaborationError: {e}"
        )
    print("dynamic_index_write_local_var_test.py PASS (no error, as expected)")


def test_writing_input_still_errors():
    # Pre-existing rule, unaffected by multi-writer support: Input[T] may
    # never be written, regardless of how many/few writer functions exist.
    src = """
from pypeline import Input

in0: Input[uint1_t]

@MAIN
def bad_writer():
    in0 = 1
"""
    _expect_elaboration_error(src, "write_input_test.py", ["in0", "read-only"])


def test_unrolled_loop_precision_positive_case():
    # Elaboration-time-constant indices (from an unrolled for loop) stay
    # precise: writer_a claims arr_w[0] and arr_w[1], writer_b claims
    # arr_w[2] and arr_w[3] -- disjoint, so this must elaborate cleanly (no
    # exception), proving the driven-path recording doesn't over-approximate
    # constant-indexed writes to "the whole array" the way a genuinely
    # variable index must.
    src = """
arr_w: Wire[uint8_t[4]]

@MAIN
def writer_a():
    for i in range(2):
        arr_w[i] = 1

@MAIN
def writer_b():
    for i in range(2, 4):
        arr_w[i] = 2
"""
    try:
        _parse(src, "unrolled_loop_precision_test.py")
    except PY_TO_LOGIC.ElaborationError as e:
        raise AssertionError(
            f"unrolled_loop_precision_test.py: expected clean elaboration "
            f"(constant-index writes from two writers covering disjoint "
            f"array elements), got ElaborationError: {e}"
        )
    print("unrolled_loop_precision_test.py PASS (no error, as expected)")


if __name__ == "__main__":
    test_overlapping_leaf_from_two_writers()
    test_whole_write_plus_field_write_conflict()
    test_nested_leaf_overlap()
    test_field_vs_enclosing_subtree_overlap()
    test_array_element_overlap()
    test_dynamic_index_write_rejected_with_multiple_writers()
    test_dynamic_index_write_global_wire_positive_case()
    test_dynamic_index_write_local_var_positive_case()
    test_writing_input_still_errors()
    test_unrolled_loop_precision_positive_case()
    print("All global_wire_errors tests passed.")
