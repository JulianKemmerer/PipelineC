#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Parity between native simulation and hardware elaboration for operators.

Three things are pinned here, each of which was broken:

1. Unary `-` on an integer widens by one bit and becomes signed. SW_LIB's
   GET_UNARY_OP_NEGATE_INT_UINT_C_CODE (`result_t = "int" + str(in_width+1)
   + "_t"`) is the authority; PY_TO_LOGIC._elab_unary and the library's
   make_soft_negate both follow it. SimVal.__neg__ used to mask back into the
   operand's own type instead, so -uint24_t(5) was 16777211 in sim against
   int25_t -5 in hardware.

2. A matcher ("generic") registration reaches native sim, not just
   elaboration. The op name has to land in the gate set that SimVal's dunders
   check; the matcher branch of register_*_operator used to return before
   adding it, so every family in register_sw_lib_replacements() was
   elaboration-only. The mutation-style tests below (a registered impl that
   returns a deliberately wrong sentinel) are what actually prove dispatch
   happens -- comparing values against the built-in cannot, because every
   soft implementation computes the same value by construction.

3. A CONSTANT shift amount is not a dispatch point. PY_TO_LOGIC._elab_binop
   routes it to the CONST_SL/CONST_SR built-in and never consults the
   registry; only a variable amount looks up an implementation. Sim used to
   dispatch on the op name regardless, which made the registered barrel
   shifter -- whose own body shifts by a constant -- recurse forever.

Plus coverage for the type-rule helpers these depend on, which had none.
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))
sys.path.insert(
    0,
    os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../../../../include/pypeline")
    ),
)

import pypeline as PL
import PY_TO_LOGIC as P2L
from pypeline import (
    SimVal,
    any_integer_t,
    hw_func,
    make_int_t,
    make_uint_t,
    register_left_operator,
    register_unary_operator,
    set_sim_soft_ops,
    sim_call,
)

# Every module-level piece of registry state an operator registration can
# touch. Snapshotted and restored around any test that registers something, so
# test order never matters and a registration in one test cannot silently
# become the implementation another test measures.
def _t(ctype):
    """Canonical name of a ctype object. make_uint_t/make_int_t build a fresh
    object per call and compare by identity, so every type assertion here goes
    through the name."""
    return PL._ctype_str(ctype)


_REGISTRY_NAMES = (
    "_operator_registry",
    "_left_operator_registry",
    "_unary_operator_registry",
    "_mux_registry",
    "_generic_operator_registry",
    "_generic_left_operator_registry",
    "_generic_unary_operator_registry",
    "_generic_mux_registry",
    "_generic_operator_cache",
    "_generic_left_operator_cache",
    "_generic_unary_operator_cache",
    "_generic_mux_cache",
    "_registered_binary_op_names",
    "_registered_unary_op_names",
    "_registered_mux_type_names",
    "_concrete_binary_op_names",
    "_concrete_unary_op_names",
    "_concrete_mux_type_names",
    "_matcher_binary_op_names",
    "_matcher_unary_op_names",
    "_matcher_mux_type_names",
)


class _isolated_registry:
    """Snapshot/restore every operator registry plus the sim dispatch policy.
    There is no unregister API by design, so tests that register have to put
    the module back the way they found it."""

    def __enter__(self):
        self._saved = {n: type(getattr(PL, n))(getattr(PL, n)) for n in _REGISTRY_NAMES}
        self._policy = PL._sim_soft_ops_policy
        return self

    def __exit__(self, *exc):
        for name, value in self._saved.items():
            live = getattr(PL, name)
            live.clear()
            if isinstance(live, dict):
                live.update(value)
            elif isinstance(live, set):
                live.update(value)
            else:  # list
                live.extend(value)
        PL._sim_soft_ops_policy = self._policy
        return False


# ── 1. Negate ────────────────────────────────────────────────────────────

_NEG_CASES = [
    (make_uint_t(1), 1),
    (make_uint_t(8), 0),
    (make_uint_t(8), 255),
    (make_uint_t(24), 5),
    (make_uint_t(32), 0xFFFFFFFF),
    (make_int_t(8), 5),
    (make_int_t(8), -128),  # signed minimum: widens, does NOT wrap
    (make_int_t(24), -5),
    (make_int_t(32), 2147483647),
]


def test_builtin_negate_widens_and_signs_like_elaboration():
    """The built-in path -- what runs when nothing is registered for NEGATE."""
    with _isolated_registry():
        set_sim_soft_ops("none")
        PL._registered_unary_op_names.discard("NEGATE")
        for t, v in _NEG_CASES:
            width = len(t)
            expected_t = make_int_t(width + 1)
            got = -SimVal(v, t)
            assert _t(got._ctype) == _t(expected_t), (
                f"-{_t(t)}({v}) ctype {_t(got._ctype)}, expected {_t(expected_t)}"
            )
            assert int(got) == -v, f"-{PL._ctype_str(t)}({v}) == {int(got)}, expected {-v}"


def test_soft_negate_return_type_matches_the_builtin_rule():
    """The library implementation and the built-in must agree, or registering
    the default soft ops would silently change every negate in a design."""
    from operators.soft_misc import make_soft_negate

    for t, _v in _NEG_CASES:
        impl = make_soft_negate(t)
        ret_t = inspect.unwrap(impl).__annotations__["return"]
        assert _t(ret_t) == f"int{len(t) + 1}_t", (
            f"make_soft_negate({_t(t)}) returns {_t(ret_t)},"
            f" built-in gives int{len(t) + 1}_t"
        )


def test_registered_negate_and_builtin_negate_agree():
    """Same value and same type whether or not the soft impl is the thing that
    runs -- this is the property that makes the SIM_SOFT_OPS default a
    performance choice rather than a correctness one."""
    from operators.soft import register_soft_negate

    for t, v in _NEG_CASES:
        out_t = make_int_t(len(t) + 1)

        @hw_func
        def negate(x: t) -> out_t:
            return -x

        with _isolated_registry():
            set_sim_soft_ops("none")
            builtin = sim_call(negate, SimVal(v, t))
        with _isolated_registry():
            register_soft_negate()
            set_sim_soft_ops("all")
            dispatched = sim_call(negate, SimVal(v, t))
        assert int(builtin) == int(dispatched) == -v
        assert _t(builtin._ctype) == _t(dispatched._ctype) == _t(out_t)


# ── 2. Matcher registrations really dispatch ─────────────────────────────

_SENTINEL = 0x5A


def _make_wrong_negate(t):
    """A deliberately wrong NEGATE. If this value comes back, the registered
    implementation is what ran; if the true negation comes back, it did not."""
    out_t = make_int_t(len(t) + 1)

    @hw_func
    def wrong_negate(x: t) -> out_t:
        return _SENTINEL

    return wrong_negate


def test_matcher_registration_dispatches_when_enabled():
    t = make_uint_t(16)
    out_t = make_int_t(17)

    @hw_func
    def negate(x: t) -> out_t:
        return -x

    with _isolated_registry():
        register_unary_operator("NEGATE", any_integer_t, _make_wrong_negate)
        set_sim_soft_ops("all")
        assert int(sim_call(negate, SimVal(7, t))) == _SENTINEL, (
            "matcher-registered NEGATE did not execute in native sim"
        )


def test_matcher_registration_is_bypassed_when_disabled():
    t = make_uint_t(16)
    out_t = make_int_t(17)

    @hw_func
    def negate(x: t) -> out_t:
        return -x

    with _isolated_registry():
        register_unary_operator("NEGATE", any_integer_t, _make_wrong_negate)
        set_sim_soft_ops("none")
        assert int(sim_call(negate, SimVal(7, t))) == -7


def test_concrete_registration_dispatches_regardless_of_policy():
    """A concrete-type registration is a deliberate, narrow override, so the
    SIM_SOFT_OPS policy (which is about the process-wide matcher defaults)
    does not switch it off."""
    t = make_uint_t(16)
    out_t = make_int_t(17)

    @hw_func
    def negate(x: t) -> out_t:
        return -x

    for policy in ("all", "none"):
        with _isolated_registry():
            register_unary_operator("NEGATE", t, _make_wrong_negate(t))
            set_sim_soft_ops(policy)
            assert int(sim_call(negate, SimVal(7, t))) == _SENTINEL, (
                f"concrete NEGATE registration ignored under SIM_SOFT_OPS={policy}"
            )


# ── 3. Constant vs. variable shift ───────────────────────────────────────


def _make_wrong_shift(t):
    amount_t = make_uint_t(max(1, (len(t) - 1).bit_length()))

    @hw_func
    def wrong_shift(x: t, amount: amount_t) -> t:
        return _SENTINEL

    return wrong_shift


def test_constant_shift_amount_does_not_dispatch():
    """Elaboration sends a constant amount to CONST_SL/CONST_SR and never
    consults the registry (PY_TO_LOGIC._elab_binop). Sim has to make the same
    split: the registered barrel shifter's own body shifts by a constant, so
    dispatching here recurses forever."""
    t = make_uint_t(16)

    @hw_func
    def shift_by_const(x: t) -> t:
        return x << 2

    with _isolated_registry():
        register_left_operator("SL", any_integer_t, _make_wrong_shift)
        set_sim_soft_ops("all")
        assert int(sim_call(shift_by_const, SimVal(3, t))) == 12, (
            "a constant shift amount reached the operator registry"
        )


def test_variable_shift_amount_does_dispatch():
    t = make_uint_t(16)
    amount_t = make_uint_t(4)

    @hw_func
    def shift_by_var(x: t, n: amount_t) -> t:
        return x << n

    with _isolated_registry():
        register_left_operator("SL", any_integer_t, _make_wrong_shift)
        set_sim_soft_ops("all")
        assert int(sim_call(shift_by_var, SimVal(3, t), SimVal(2, amount_t))) == _SENTINEL, (
            "a variable shift amount did not reach the operator registry"
        )


# ── 4. Every default soft family runs, and agrees ────────────────────────

_U8 = make_uint_t(8)
_I8 = make_int_t(8)
_U4 = make_uint_t(4)


def _soft_family_cases():
    """(name, hw_func, args, expected value, expected ctype) for each family
    register_sw_lib_replacements() installs."""
    u8, i8, u4 = _U8, _I8, _U4
    i9 = make_int_t(9)
    u1 = make_uint_t(1)

    @hw_func
    def f_sl(x: u8, n: u4) -> u8:
        return x << n

    @hw_func
    def f_sr(x: u8, n: u4) -> u8:
        return x >> n

    @hw_func
    def f_lt_u(a: u8, b: u8) -> u1:
        return a < b

    @hw_func
    def f_lt_i(a: i8, b: i8) -> u1:
        return a < b

    @hw_func
    def f_gte_u(a: u8, b: u8) -> u1:
        return a >= b

    @hw_func
    def f_div_u(a: u8, b: u8) -> u8:
        return a / b

    @hw_func
    def f_div_i(a: i8, b: i8) -> i8:
        return a / b

    @hw_func
    def f_mod_u(a: u8, b: u8) -> u8:
        return a % b

    @hw_func
    def f_mod_i(a: i8, b: i8) -> i8:
        return a % b

    @hw_func
    def f_neg_u(a: u8) -> i9:
        return -a

    @hw_func
    def f_neg_i(a: i8) -> i9:
        return -a

    return [
        ("SL  var", f_sl, (SimVal(3, u8), SimVal(2, u4)), 12, u8),
        ("SR  var", f_sr, (SimVal(48, u8), SimVal(2, u4)), 12, u8),
        ("LT  uint", f_lt_u, (SimVal(3, u8), SimVal(9, u8)), 1, u1),
        ("LT  int", f_lt_i, (SimVal(-3, i8), SimVal(9, i8)), 1, u1),
        ("GTE uint", f_gte_u, (SimVal(9, u8), SimVal(9, u8)), 1, u1),
        ("DIV uint", f_div_u, (SimVal(200, u8), SimVal(7, u8)), 28, u8),
        ("DIV int", f_div_i, (SimVal(-100, i8), SimVal(7, i8)), -14, i8),
        ("MOD uint", f_mod_u, (SimVal(200, u8), SimVal(7, u8)), 4, u8),
        ("MOD int", f_mod_i, (SimVal(-100, i8), SimVal(7, i8)), -2, i8),
        ("NEG uint", f_neg_u, (SimVal(200, u8),), -200, i9),
        ("NEG int", f_neg_i, (SimVal(-100, i8),), 100, i9),
    ]


def test_default_soft_families_run_without_recursing():
    """The RecursionError guard. With every default matcher registration
    dispatchable, each family must terminate and return the built-in's value
    and type. DIV/MOD go through the barrel shifter internally, so a
    regression in the constant-shift split takes these down too."""
    from operators.soft import register_sw_lib_replacements

    import operators.soft as _soft

    with _isolated_registry():
        # register_sw_lib_replacements() de-dupes once per process; these tests
        # deliberately re-run it inside a snapshot, so clear the one-shot flag.
        _soft._sw_lib_replacements_registered = False
        register_sw_lib_replacements()
        set_sim_soft_ops("all")
        for name, fn, args, expected, expected_t in _soft_family_cases():
            got = sim_call(fn, *args)
            assert int(got) == expected, f"{name}: got {int(got)}, expected {expected}"
            assert _t(got._ctype) == _t(expected_t), (
                f"{name}: ctype {_t(got._ctype)}, expected {_t(expected_t)}"
            )


def test_default_soft_families_agree_with_builtins():
    from operators.soft import register_sw_lib_replacements
    import operators.soft as _soft

    cases = _soft_family_cases()
    with _isolated_registry():
        set_sim_soft_ops("none")
        builtin = [int(sim_call(fn, *args)) for _n, fn, args, _e, _t in cases]
    with _isolated_registry():
        _soft._sw_lib_replacements_registered = False
        register_sw_lib_replacements()
        set_sim_soft_ops("all")
        dispatched = [int(sim_call(fn, *args)) for _n, fn, args, _e, _t in cases]
    for (name, _f, _a, _e, _t), b, d in zip(cases, builtin, dispatched):
        assert b == d, f"{name}: built-in {b} != soft {d}"


# ── 5. Scoped registrations must not leak ────────────────────────────────


def test_scoped_generic_registration_does_not_leak_globally():
    """_resolve_generic_* memoizes a resolved implementation into the global
    concrete registry. Doing that for an entry that came from a scope=
    registration leaked it past scope exit, so every other function in the
    design silently picked up one function's scoped implementation -- wrong
    hardware, not just wrong sim."""

    def scope_fn():
        pass

    def factory(t):
        return f"IMPL_{PL._ctype_str(t)}"

    with _isolated_registry():
        before_concrete = dict(PL._unary_operator_registry)
        before_names = set(PL._registered_unary_op_names)
        register_unary_operator("NEGATE", any_integer_t, factory, scope=scope_fn)
        saved = PL._push_scoped_registrations(scope_fn)
        assert PL._resolve_generic_unary_operator("NEGATE", "uint8_t") == "IMPL_uint8_t"
        PL._pop_scoped_registrations(saved)
        assert PL._unary_operator_registry == before_concrete, (
            "scoped generic impl leaked into the global registry:"
            f" {set(PL._unary_operator_registry) - set(before_concrete)}"
        )
        assert PL._registered_unary_op_names == before_names, (
            "scoped generic op name leaked into the sim gate set:"
            f" {PL._registered_unary_op_names - before_names}"
        )


def test_global_generic_registration_is_still_memoized():
    """The scoped-leak fix must not cost the memoization for ordinary global
    matcher registrations -- that is what keeps repeated resolutions cheap."""

    def factory(t):
        return f"IMPL_{PL._ctype_str(t)}"

    with _isolated_registry():
        register_unary_operator("NEGATE", any_integer_t, factory)
        assert PL._resolve_generic_unary_operator("NEGATE", "uint8_t") == "IMPL_uint8_t"
        assert PL._unary_operator_registry.get(("NEGATE", "uint8_t")) == "IMPL_uint8_t"


# ── 6. Type-rule helpers ─────────────────────────────────────────────────


def test_literal_ctype_rules_agree_between_sim_and_elaboration():
    """pypeline._infer_literal_ctype and PY_TO_LOGIC._infer_const_ctype are
    duplicate implementations of one rule. They agree today only because
    C_TO_LOGIC.BOOL_C_TYPE happens to be "uint1_t"; nothing asserted it."""
    values = [0, 1, 2, 3, 7, 8, 255, 256, 65535, 1 << 31, -1, -2, -128, -129, -(1 << 31)]
    for v in values:
        sim_t = PL._infer_literal_ctype(v)
        elab_t = P2L._infer_const_ctype(v)
        assert sim_t == elab_t, f"literal {v}: sim {sim_t!r} vs elaboration {elab_t!r}"


def test_arith_promote_rules():
    assert PL._arith_promote("uint8_t", "uint16_t") == ("uint8_t", "uint16_t", False)
    assert PL._arith_promote("int8_t", "int16_t") == ("int8_t", "int16_t", True)
    # Mismatched signedness: the unsigned side gains a bit and becomes signed.
    assert PL._arith_promote("int32_t", "uint32_t") == ("int32_t", "int33_t", True)
    assert PL._arith_promote("uint32_t", "int32_t") == ("int33_t", "int32_t", True)
    # Non-integer types pass through untouched.
    assert PL._arith_promote("my_struct_t", "uint8_t") == ("my_struct_t", "uint8_t", None)


def test_arith_output_ctype_widths():
    assert _t(PL._arith_output_ctype("add", "uint8_t", "uint16_t", False)) == "uint17_t"
    assert _t(PL._arith_output_ctype("sub", "uint8_t", "uint16_t", False)) == "uint16_t"
    assert _t(PL._arith_output_ctype("sub", "int8_t", "int16_t", True)) == "int17_t"
    assert _t(PL._arith_output_ctype("mul", "uint8_t", "uint16_t", False)) == "uint24_t"
    assert _t(PL._arith_output_ctype("div", "uint8_t", "uint16_t", False)) == "uint16_t"
    assert _t(PL._arith_output_ctype("mod", "int8_t", "int16_t", True)) == "int16_t"


# ── 7. Policy parsing ────────────────────────────────────────────────────


def test_sim_soft_ops_policy_spellings():
    with _isolated_registry():
        for spec in ("all", "1", None):
            set_sim_soft_ops(spec)
            assert PL._sim_soft_ops_allows("DIV")
            assert PL._sim_soft_ops_allows("ANYTHING")
        for spec in ("none", "0", ""):
            set_sim_soft_ops(spec)
            assert not PL._sim_soft_ops_allows("DIV")
        set_sim_soft_ops("NEGATE,LT,LTE,GT,GTE")
        assert PL._sim_soft_ops_allows("NEGATE")
        assert PL._sim_soft_ops_allows("GTE")
        assert not PL._sim_soft_ops_allows("DIV")
        assert not PL._sim_soft_ops_allows("SL")
        # Spelling is normalised: whitespace and case do not matter.
        set_sim_soft_ops(" negate , lt ")
        assert PL._sim_soft_ops_allows("NEGATE") and PL._sim_soft_ops_allows("LT")


def test_sim_soft_ops_policy_switches_the_gate_set():
    """Toggling the policy has to rebuild the gate sets SimVal's dunders read,
    not just record a preference."""
    with _isolated_registry():
        register_unary_operator("NEGATE", any_integer_t, _make_wrong_negate)
        set_sim_soft_ops("all")
        assert "NEGATE" in PL._registered_unary_op_names
        set_sim_soft_ops("none")
        assert "NEGATE" not in PL._registered_unary_op_names
        set_sim_soft_ops("NEGATE")
        assert "NEGATE" in PL._registered_unary_op_names


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
