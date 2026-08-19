import copy
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from typing import NamedTuple

from pypeline import (
    MAIN,
    cast,
    hw_func,
    int8_t,
    int16_t,
    sim_call,
    sim_reset,
    struct,
    uint1_t,
    uint4_t,
    uint8_t,
    uint16_t,
)

# ── uint8_t(x) vs `tmp: uint8_t = x` -- must be identical, every quadrant ──
# (widening/narrowing x signed/unsigned). Each pair below does the identical
# conversion two ways; the tests assert they always agree.


@MAIN
def cast_widen_unsigned(a: uint4_t) -> uint16_t:
    return uint16_t(a)


@MAIN
def assign_widen_unsigned(a: uint4_t) -> uint16_t:
    b: uint16_t = a
    return b


@MAIN
def cast_narrow_unsigned(a: uint16_t) -> uint4_t:
    return uint4_t(a)


@MAIN
def assign_narrow_unsigned(a: uint16_t) -> uint4_t:
    b: uint4_t = a
    return b


@MAIN
def cast_widen_signed(a: int8_t) -> int16_t:
    return int16_t(a)


@MAIN
def assign_widen_signed(a: int8_t) -> int16_t:
    b: int16_t = a
    return b


@MAIN
def cast_narrow_signed(a: int16_t) -> int8_t:
    return int8_t(a)


@MAIN
def assign_narrow_signed(a: int16_t) -> int8_t:
    b: int8_t = a
    return b


@MAIN
def cast_narrow_unsigned_from_signed(a: int16_t) -> uint8_t:
    return uint8_t(a)


@MAIN
def assign_narrow_unsigned_from_signed(a: int16_t) -> uint8_t:
    b: uint8_t = a
    return b


@MAIN
def cast_widen_signed_from_unsigned(a: uint8_t) -> int16_t:
    return int16_t(a)


@MAIN
def assign_widen_signed_from_unsigned(a: uint8_t) -> int16_t:
    b: int16_t = a
    return b


@MAIN
def identity_cast(a: uint8_t) -> uint8_t:
    return uint8_t(a)


def _assert_cast_matches_assign(cast_fn, assign_fn, values):
    sim_reset()
    for v in values:
        c = int(sim_call(cast_fn, v))
        sim_reset()
        a = int(sim_call(assign_fn, v))
        sim_reset()
        assert c == a, f"{cast_fn.__name__}({v}) = {c} != {assign_fn.__name__}({v}) = {a}"


def test_cast_matches_assign_widen_unsigned():
    _assert_cast_matches_assign(cast_widen_unsigned, assign_widen_unsigned, [0, 1, 7, 15])


def test_cast_matches_assign_narrow_unsigned():
    _assert_cast_matches_assign(
        cast_narrow_unsigned, assign_narrow_unsigned, [0, 1, 15, 16, 255, 4095, 65535]
    )


def test_cast_matches_assign_widen_signed():
    _assert_cast_matches_assign(cast_widen_signed, assign_widen_signed, [0, 1, -1, 127, -128])


def test_cast_matches_assign_narrow_signed():
    # This is native-sim-only (see nested_truncate_test.py for the same
    # signed-narrowing quadrant confirmed against real GHDL, which is what
    # actually exercised the VHDL.py sign-preserving-resize bug this fix
    # closed -- native sim's _sim_cast was always correct here).
    _assert_cast_matches_assign(
        cast_narrow_signed, assign_narrow_signed, [0, 1, -1, 127, -128, 300, -300, 32767, -32768]
    )


def test_cast_matches_assign_narrow_unsigned_from_signed():
    _assert_cast_matches_assign(
        cast_narrow_unsigned_from_signed,
        assign_narrow_unsigned_from_signed,
        [0, 1, -1, 200, -200, 300, -300],
    )


def test_cast_matches_assign_widen_signed_from_unsigned():
    _assert_cast_matches_assign(
        cast_widen_signed_from_unsigned, assign_widen_signed_from_unsigned, [0, 1, 127, 200, 255]
    )


def test_identity_cast():
    sim_reset()
    assert int(sim_call(identity_cast, 200)) == 200


# ── cast in every syntactic position ──


@struct
class pair_t(NamedTuple):
    x: uint8_t
    y: uint8_t


@hw_func
def add_u8(a: uint8_t, b: uint8_t) -> uint8_t:
    return a + b


@MAIN
def cast_as_call_arg(a: int16_t, b: uint8_t) -> uint8_t:
    return add_u8(uint8_t(a), b)


@MAIN
def cast_as_struct_field_init(a: int16_t) -> pair_t:
    return pair_t(x=uint8_t(a), y=0)


@MAIN
def cast_in_expression(a: int16_t, b: int16_t) -> uint8_t:
    return uint8_t(a) + uint8_t(b)


@MAIN
def cast_in_ternary(sel: uint1_t, a: int16_t, b: uint8_t) -> uint8_t:
    return uint8_t(a) if sel else b


def test_cast_as_call_arg():
    sim_reset()
    r = sim_call(cast_as_call_arg, 300, 10)
    assert int(r) == (44 + 10) % 256, r


def test_cast_as_struct_field_init():
    sim_reset()
    r = sim_call(cast_as_struct_field_init, 300)
    assert int(r.x) == 44 and int(r.y) == 0, r


def test_cast_in_expression():
    sim_reset()
    r = sim_call(cast_in_expression, 300, 12)
    assert int(r) == (44 + 12) % 256, r


def test_cast_in_ternary():
    sim_reset()
    r_true = sim_call(cast_in_ternary, 1, 300, 5)
    sim_reset()
    r_false = sim_call(cast_in_ternary, 0, 300, 5)
    assert int(r_true) == 44, r_true
    assert int(r_false) == 5, r_false


# ── copy-protocol regression: the exact bug _CastDispatchMeta exists to
# prevent (see pypeline.py's struct()/_CastDispatchMeta docstrings). A
# one-field struct with a registered NON-identity cast from its own field's
# type must still deepcopy/copy correctly -- copy.deepcopy/copy.copy
# reconstruct via cls.__new__(cls, single_value), the exact same call shape
# as a cast, and only a metaclass __call__ (not a __new__ override) can tell
# the two apart. ──


@struct
class doubled_t(NamedTuple):
    v: uint8_t


@cast
def _double_it(x: uint8_t) -> doubled_t:
    return doubled_t(v=x * 2)


def test_deepcopy_and_copy_not_reinterpreted_as_cast():
    o = doubled_t(v=7)
    d = copy.deepcopy(o)
    c = copy.copy(o)
    assert int(d.v) == 7, f"deepcopy silently re-ran the registered cast: {d}"
    assert int(c.v) == 7, f"copy silently re-ran the registered cast: {c}"
    # Real T(x) cast syntax must still dispatch correctly.
    casted = doubled_t(uint8_t(9))
    assert int(casted.v) == 18, f"cast dispatch broken: {casted}"


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
