# pyright: reportInvalidTypeForm=none
"""@cast on user-written hw_funcs -- both a plain struct-to-struct converter
with real logic (not just field rewiring) and the library-registered float/
int conversions (make_float_converter/make_float_to_int/make_int_to_float in
floating_point.py, each self-registering via register_cast), proving @cast
carries real computation, not just structural rewiring like the interface
wrap/unwrap casts in cast_interface_test.py.
"""
import sys, os

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
from typing import NamedTuple

from pypeline import MAIN, cast, int32_t, sim_call, sim_reset, struct, uint8_t, wires

from floating_point import float32_t, float64_t

# ── a hand-written struct-to-struct cast with real logic (not a rewire):
# packs a scalar into a {lo, hi} split struct. ──


@struct
class split_t(NamedTuple):
    lo: uint8_t
    hi: uint8_t


@cast
@wires
def _split_from_int32(x: int32_t) -> split_t:
    lo: uint8_t = x
    hi: uint8_t = x[15:8]
    return split_t(lo=lo, hi=hi)


@MAIN
def cast_int32_to_split(x: int32_t) -> split_t:
    return split_t(x)


def test_user_struct_cast_with_real_logic():
    sim_reset()
    r = sim_call(cast_int32_to_split, 0x1234)
    assert int(r.lo) == 0x34, r
    assert int(r.hi) == 0x12, r


# ── library float/int casts (make_float_converter/make_float_to_int/
# make_int_to_float), self-registered from floating_point.py. Proves the
# cast mechanism carries real logic end to end, driven purely through cast
# syntax (T(x)), not a direct call to the factory-returned function. ──


@MAIN
def cast_f32_to_f64(x: float32_t) -> float64_t:
    return float64_t(x)


@MAIN
def cast_f64_to_i32(x: float64_t) -> int32_t:
    return int32_t(x)


@MAIN
def cast_i32_to_f64(x: int32_t) -> float64_t:
    return float64_t(x)


def _f32_bits(sign, exp, man):
    return float32_t(sign=sign, exp=exp, man=man)


def test_float32_to_float64_cast():
    sim_reset()
    # 3.5 = 1.75 * 2^1: sign=0, exp=128 (bias 127 + 1), man=0.75*2^23
    x = _f32_bits(0, 128, int(0.75 * (1 << 23)))
    r = sim_call(cast_f32_to_f64, x)
    assert int(r.sign) == 0, r
    # Round-trip through the (separately tested) float64->int32 cast rather
    # than hand-deriving the widened exponent/mantissa bit pattern here.
    sim_reset()
    back = sim_call(cast_f64_to_i32, r)
    assert int(back) == 3, (r, back)


def test_float_to_int_cast():
    sim_reset()
    x = _f32_bits(0, 128, int(0.75 * (1 << 23)))  # 3.5
    f64 = sim_call(cast_f32_to_f64, x)
    sim_reset()
    r = sim_call(cast_f64_to_i32, f64)
    assert int(r) == 3, r


def test_int_to_float_cast():
    sim_reset()
    r = sim_call(cast_i32_to_f64, 7)
    # 7 = 1.75 * 2^2: exp = 1023 + 2
    assert int(r.exp) == 1025, r


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
