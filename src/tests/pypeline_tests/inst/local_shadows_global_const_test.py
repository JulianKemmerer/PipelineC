# pyright: reportInvalidTypeForm=none
"""A hardware local must shadow a same-named Python global/closure name.

Elaboration folds constants by eval()ing expressions against
{**module_globals, **const_env} (PY_TO_LOGIC._try_eval_const), a namespace that
never contained the function's own hardware locals.  So whenever a local had the
same name as a module global (or a factory-closure variable), the GLOBAL won --
the opposite of both Python's own scoping and _elab_name's env-first lookup, which
native sim follows.  Symptoms ranged from a raw KeyError out of _ref_toks_to_ctype
(`return o.p0.a` where the global's `.p0.a` is a NamedTuple) to silent miscompiles
(a constant-folded array index, a stale const_env value used after the name became
hardware).

Checked in-process: native sim result vs. the elaborated Logic() graph
(wire_driven_by / submodule_instances / wires), since several of these variants
never raise on either side of the fix -- they just build the wrong hardware.
"""
import os
import sys
from types import SimpleNamespace
from typing import NamedTuple

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../"))

from pypeline import (
    Reg,
    hw_func,
    pipeline_latency,
    sim_call,
    sim_reset,
    struct,
    uint2_t,
    uint8_t,
)


@struct
class pair_t(NamedTuple):
    a: uint8_t
    b: uint8_t


@struct
class wrap_t(NamedTuple):
    p0: pair_t


@struct
class inner_t(NamedTuple):
    a: pair_t


@struct
class outer_t(NamedTuple):
    p0: inner_t


# Module-level Python values that shadow (are shadowed by) hardware locals below.
# o.p0.a is a COMPOUND value (pair_t) on this global, but a uint8_t on the local.
o = outer_t(p0=inner_t(a=pair_t(a=1, b=2)))
# s.p0.a is a str on this global.
s = SimpleNamespace(p0=SimpleNamespace(a="hi"))
# g.p0.a is a plain int on this global.
g = SimpleNamespace(p0=SimpleNamespace(a=77))
# Same, reached through a @pipeline_latency child (the sim_call -> prepare path).
q = outer_t(p0=inner_t(a=pair_t(a=1, b=2)))
IDX = 2  # shadowed by an index PARAMETER named IDX
W = 4  # shadowed by a parameter named W, but still the array-size annotation


@hw_func
def make_wrap(x: uint8_t) -> wrap_t:
    w: wrap_t
    w.p0.a = x
    w.p0.b = x
    return w


@hw_func
def compound_shadow(x: uint8_t) -> uint8_t:
    o: wrap_t = make_wrap(x)
    return o.p0.a


@hw_func
def str_shadow(x: uint8_t) -> uint8_t:
    s: wrap_t = make_wrap(x)
    return s.p0.a


@hw_func
def int_shadow(x: uint8_t) -> uint8_t:
    g: wrap_t = make_wrap(x)
    return g.p0.a


@hw_func
def index_shadow(arr: uint8_t[4], IDX: uint2_t) -> uint8_t:
    return arr[IDX]


@hw_func
def const_then_hw(x: uint8_t) -> uint8_t:
    b = 0  # elaboration-time constant ...
    b = x  # ... then the same name becomes hardware
    return b + 1


@hw_func
def aug_after_hw(x: uint8_t) -> uint8_t:
    b = 0
    b = x
    b += 1
    return b


@hw_func
def comprehension_bound_name(i: uint8_t) -> uint8_t:
    # The `i` inside the comprehension is bound BY the comprehension, not the
    # hardware parameter `i`, so this must still fold to a Python list.
    c = [i * 3 for i in range(4)]
    return i + c[2]


@hw_func
def ann_shadow(W: uint8_t) -> uint8_t:
    # A local variable's ANNOTATION is never evaluated by Python, and an array
    # size can only mean the module-global W == 4, not the hardware parameter.
    arr: uint8_t[W] = [W, W, W, W]
    return arr[3]


@pipeline_latency(1)
def delay_one(x: uint8_t) -> uint8_t:
    saved: Reg[uint8_t]
    result: uint8_t = saved
    saved = x
    return result


@hw_func
def pipelined_compound_shadow(x: uint8_t) -> uint8_t:
    q: wrap_t = make_wrap(delay_one(x))
    return q.p0.a


def _logic_of(fn, func_name):
    """Elaborate fn and return the Logic() built for func_name."""
    import PY_TO_LOGIC as py

    state = py.ELABORATE_LIVE_ROOTS([fn])
    for name, logic in state.FuncLogicLookupTable.items():
        if name == func_name or name.startswith(func_name + "_"):
            return logic
    raise AssertionError(
        f"{func_name} missing from FuncLogicLookupTable: {sorted(state.FuncLogicLookupTable)}"
    )


def _driver(logic):
    return logic.wire_driven_by.get("return_output") or ""


def _submodules(logic):
    return sorted(logic.submodule_instances.keys())


def test_compound_global_shadowed_by_local():
    """The original crash: KeyError: 'uint8_t' out of _ref_toks_to_ctype."""
    sim_reset()
    assert int(sim_call(compound_shadow, 5)) == 5
    logic = _logic_of(compound_shadow, "compound_shadow")
    driver = _driver(logic)
    assert "REF_RD" in driver, driver
    assert any("make_wrap" in sub for sub in _submodules(logic)), _submodules(logic)
    print("test_compound_global_shadowed_by_local PASS")


def test_str_global_shadowed_by_local():
    """A str-valued global would be emitted as a string-literal CONST wire."""
    sim_reset()
    assert int(sim_call(str_shadow, 6)) == 6
    logic = _logic_of(str_shadow, "str_shadow")
    bad = [w for w in logic.wires if "hi" in w]
    assert not bad, f"string literal from the shadowed global leaked into hardware: {bad}"
    assert "REF_RD" in _driver(logic), _driver(logic)
    print("test_str_global_shadowed_by_local PASS")


def test_int_global_shadowed_by_local():
    """Sanity: an int-valued global already lost to the local; keep it that way."""
    sim_reset()
    assert int(sim_call(int_shadow, 7)) == 7
    logic = _logic_of(int_shadow, "int_shadow")
    bad = [w for w in logic.wires if w.startswith("CONST_77")]
    assert not bad, bad
    assert "REF_RD" in _driver(logic), _driver(logic)
    print("test_int_global_shadowed_by_local PASS")


def test_index_shadowed_by_local_is_not_const_folded():
    """arr[IDX] with a hardware IDX must stay a variable read, not fold to arr[2]."""
    sim_reset()
    assert int(sim_call(index_shadow, [10, 20, 30, 40], 1)) == 20
    logic = _logic_of(index_shadow, "index_shadow")
    subs = _submodules(logic)
    assert any("VAR_REF_RD" in sub for sub in subs), (
        f"index const-folded to the module global IDX={IDX}: {subs}"
    )
    print("test_index_shadowed_by_local_is_not_const_folded PASS")


def test_const_env_value_not_reused_after_name_becomes_hardware():
    """b = 0; b = x; b + 1 -- the stale const_env b == 0 must not fold to 1."""
    sim_reset()
    assert int(sim_call(const_then_hw, 9)) == 10
    logic = _logic_of(const_then_hw, "const_then_hw")
    subs = _submodules(logic)
    assert any("BIN_OP" in sub for sub in subs), f"b + 1 was const-folded: {subs}"
    print("test_const_env_value_not_reused_after_name_becomes_hardware PASS")


def test_aug_assign_after_name_becomes_hardware():
    """b += 1 must update the hardware b, not the stale const_env entry."""
    sim_reset()
    assert int(sim_call(aug_after_hw, 9)) == 10
    logic = _logic_of(aug_after_hw, "aug_after_hw")
    subs = _submodules(logic)
    assert any("BIN_OP" in sub for sub in subs), f"b += 1 updated const_env: {subs}"
    print("test_aug_assign_after_name_becomes_hardware PASS")


def test_comprehension_bound_name_still_folds():
    """A name bound INSIDE the expression is not the hardware local."""
    sim_reset()
    assert int(sim_call(comprehension_bound_name, 5)) == 11
    logic = _logic_of(comprehension_bound_name, "comprehension_bound_name")
    assert any(w.startswith("CONST_6_") for w in logic.wires), sorted(logic.wires)
    print("test_comprehension_bound_name_still_folds PASS")


def test_annotation_still_sees_the_global():
    """Annotations are never evaluated by Python, so the global must win there."""
    sim_reset()
    assert int(sim_call(ann_shadow, 3)) == 3
    logic = _logic_of(ann_shadow, "ann_shadow")
    # The array was sized by the module global W == 4, not by the parameter.
    assert "uint8_t[4]" in set(logic.wire_to_c_type.values()), sorted(
        set(logic.wire_to_c_type.values())
    )
    print("test_annotation_still_sees_the_global PASS")


def test_sim_call_prepare_path():
    """sim_call of a function reaching a @pipeline_latency child elaborates too."""
    sim_reset()
    outputs = [int(sim_call(pipelined_compound_shadow, x)) for x in (3, 8, 17)]
    assert outputs == [0, 3, 8], outputs
    print("test_sim_call_prepare_path PASS")


if __name__ == "__main__":
    test_compound_global_shadowed_by_local()
    test_str_global_shadowed_by_local()
    test_int_global_shadowed_by_local()
    test_index_shadowed_by_local_is_not_const_folded()
    test_const_env_value_not_reused_after_name_becomes_hardware()
    test_aug_assign_after_name_becomes_hardware()
    test_comprehension_bound_name_still_folds()
    test_annotation_still_sees_the_global()
    test_sim_call_prepare_path()
    print("All local_shadows_global_const tests passed.")
