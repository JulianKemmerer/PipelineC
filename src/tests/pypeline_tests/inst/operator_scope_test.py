# pyright: reportInvalidTypeForm=none
"""In-process elaboration test for the matcher-based generic operator registry
(src/pypeline.py's register_operator/_resolve_generic_operator + the new
_elab_compare registry consultation in src/PY_TO_LOGIC.py).

Checked directly via PY_TO_LOGIC.PARSE_FILE + FuncLogicLookupTable /
submodule_instances, not sim_call or a full pipelinec build -- same rationale
as two_factory_wrappers_test.py: this is about *what got instantiated*, which
neither native sim (never touches FuncLogicLookupTable) nor a bare "does it
elaborate" check can see.

Covers:
  1. A generic (any_integer_t) registration resolves for a width no exact
     registration names, and the design's `+` uses it (a soft_ripple_add_*
     submodule appears; no built-in BIN_OP_PLUS_uint9_t_uint9_t does).
  2. Memoization: two call sites at the same width share one Logic() entity
     (one soft_ripple_add_uint9_t_uint9_t func_name, two instances).
  3. INFERRED pins one exact (op, type, type) back to the built-in path even
     though a broader generic registration is globally active for that op --
     an exact registration always takes priority over a generic (matcher)
     one, so this is the escape hatch for "everything soft except this one
     width/function".
  4. Comparison operators (previously never consulted the registry at all)
     now dispatch to a registered implementation.

NOTE: scope= registrations only take effect for functions reached through
_elaborate_live_func (factory closures, or as the target of a registered
operator) -- PARSE_FILE Step 7 elaborates plain top-level @hw_func
definitions directly, without going through that push/pop path, so scope=
on a bare top-level function is a no-op today. This test therefore exercises
INFERRED via a global exact-type override (item 3) rather than scope=; the
Step-7 gap is a pre-existing limitation, not something this change fixes.
"""
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "..",
        "..",
        "include",
        "pypeline",
    ),
)

from pypeline import (
    MAIN,
    hw_func,
    uint9_t,
    uint7_t,
    uint1_t,
    any_integer_t,
    INFERRED,
    register_operator,
)

from operators.soft_add import make_soft_ripple_add
from operators.soft_cmp import make_soft_sub_cmp

register_operator("PLUS", any_integer_t, any_integer_t, make_soft_ripple_add)
register_operator("GT", any_integer_t, any_integer_t, make_soft_sub_cmp("GT"))
# Exact registration always beats a generic one: uint7_t + uint7_t is pinned
# back to the built-in inferred adder even though the broader any_integer_t
# registration above is globally active for every other width.
register_operator("PLUS", uint7_t, uint7_t, INFERRED)


@hw_func
def add_twice(a: uint9_t, b: uint9_t, c: uint9_t) -> uint9_t:
    # Two call sites at the identical (op, l, r) key -- must memoize to one
    # Logic() entity, not elaborate the factory twice.
    x: uint9_t = a + b
    y: uint9_t = x + c
    return y


@hw_func
def add_inferred_pin(a: uint7_t, b: uint7_t) -> uint7_t:
    return a + b


@hw_func
def gt_check(a: uint9_t, b: uint9_t) -> uint1_t:
    return a > b


@MAIN
def op_scope_main(a: uint9_t, b: uint9_t, c: uint9_t) -> uint9_t:
    s = add_twice(a, b, c)
    pinned = add_inferred_pin(a, b)
    ok: uint1_t = gt_check(a, b)
    result: uint9_t = s
    if ok:
        result = pinned
    return result


def test_generic_operator_registry():
    import tempfile
    import PY_TO_LOGIC
    import SYN

    SYN.SYN_OUTPUT_DIRECTORY = tempfile.mkdtemp(prefix="operator_scope_test_")
    parser_state = PY_TO_LOGIC.PARSE_FILE(os.path.abspath(__file__))

    all_func_names = set(parser_state.FuncLogicLookupTable.keys())
    all_instantiated = set()
    for logic in parser_state.FuncLogicLookupTable.values():
        all_instantiated.update(logic.submodule_instances.values())

    # (1) The generic soft adder resolved and was instantiated for uint9_t.
    soft_add_names = {n for n in all_instantiated if "soft_ripple_add" in n}
    assert soft_add_names, (
        f"expected a soft_ripple_add_* entity to be instantiated for the "
        f"generic PLUS registration; instantiated={sorted(all_instantiated)}"
    )

    # No built-in BIN_OP_PLUS_uint9_t_uint9_t anywhere -- the generic
    # registration must have fully overridden the built-in path for this pair.
    assert not any(
        n.startswith("BIN_OP_PLUS_uint9_t_uint9_t") for n in all_instantiated
    ), f"built-in BIN_OP_PLUS_uint9_t_uint9_t leaked through: {sorted(all_instantiated)}"

    # (2) Memoization: add_twice has two `+` call sites at the same (PLUS,
    # uint9_t, uint9_t) key -- both must resolve to the SAME entity name.
    assert len(soft_add_names) == 1, (
        f"expected exactly one soft-add entity name (memoized across both "
        f"call sites in add_twice), got {sorted(soft_add_names)}"
    )
    add_twice_logic = parser_state.FuncLogicLookupTable[
        next(k for k in all_func_names if k.endswith("add_twice"))
    ]
    plus_insts = [
        fn for fn in add_twice_logic.submodule_instances.values() if "soft_ripple_add" in fn
    ]
    assert len(plus_insts) == 2 and len(set(plus_insts)) == 1, (
        f"add_twice should instantiate the same memoized soft-add func_name "
        f"twice (two instances, one entity): {plus_insts}"
    )

    # (3) INFERRED pin: the exact uint7_t/uint7_t registration overrides the
    # broader global generic registration, so add_inferred_pin's `+` uses the
    # built-in path even though every other width in this design goes soft.
    assert any(
        n.startswith("BIN_OP_PLUS_uint7_t_uint7_t") for n in all_instantiated
    ), (
        f"the exact INFERRED registration for uint7_t/uint7_t should have "
        f"produced a built-in BIN_OP_PLUS_uint7_t_uint7_t instance somewhere; "
        f"instantiated={sorted(all_instantiated)}"
    )
    assert not any(
        "soft_ripple_add" in n and "uint7_t" in n for n in all_instantiated
    ), f"uint7_t PLUS should not have used the generic soft adder: {sorted(all_instantiated)}"

    # (4) Comparison operators now consult the registry: gt_check's `>`
    # resolves to the registered soft comparator, not a built-in BIN_OP_GT.
    soft_cmp_names = {n for n in all_instantiated if "soft_sub_cmp" in n}
    assert soft_cmp_names, (
        f"expected a soft_sub_cmp_* entity for the registered GT operator; "
        f"instantiated={sorted(all_instantiated)}"
    )
    assert not any(
        n.startswith("BIN_OP_GT_uint9_t_uint9_t") for n in all_instantiated
    ), f"built-in BIN_OP_GT_uint9_t_uint9_t leaked through: {sorted(all_instantiated)}"

    print("test_generic_operator_registry passed")


if __name__ == "__main__":
    test_generic_operator_registry()
