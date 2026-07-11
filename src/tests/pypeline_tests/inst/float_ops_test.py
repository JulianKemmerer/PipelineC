# pyright: reportInvalidTypeForm=none
import sys, os

# Path for pypeline import
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)
# Path for floating_point (include/pypeline) import
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
from pypeline import MAIN, struct, NamedTuple, sim_call, int32_t
from floating_point import (
    float32_t,
    float64_t,
    float32_to_float64,
    float64_to_float32,
    float64_to_int32,
    int32_to_float64,
)


# ─────────────────────────────────────────────
# Elaboration/synthesis coverage: bare +, -, *, / on both predefined widths,
# exercised through @MAIN entry points (matches float32_add_test.py's
# float_add_32_main pattern).
# ─────────────────────────────────────────────


@MAIN
def float32_add_main(a: float32_t, b: float32_t) -> float32_t:
    return a + b


@MAIN
def float32_sub_main(a: float32_t, b: float32_t) -> float32_t:
    return a - b


@MAIN
def float32_mul_main(a: float32_t, b: float32_t) -> float32_t:
    return a * b


@MAIN
def float32_div_main(a: float32_t, b: float32_t) -> float32_t:
    return a / b


# float64 +, -, *, /, and float32<->float64/int32 conversions are exercised
# only via native sim below (test_bare_operators_native_sim/test_conversions),
# not through @MAIN -- float64's wider mantissa (52 vs 23 bits) makes its
# --comb synthesis substantially more expensive than float32's, and native
# sim already gives full bit-accurate coverage of the same arithmetic without
# paying that cost.

# ─────────────────────────────────────────────
# Native-simulation correctness tests
# ─────────────────────────────────────────────


def test_bare_operators_native_sim():
    """Bare +, -, *, / on float32_t/float64_t called directly as plain
    Python (no sim_call) -- exercises the struct-operator dispatch dunders
    (__add__/__sub__/__mul__/__truediv__) added to pypeline.py's struct()
    decorator, which is what makes `a + b` on registered float types work
    outside of hardware elaboration in the first place."""
    cases = [
        (5.0, 3.0, 8.0, 2.0, 15.0, 5.0 / 3.0),
        (-2.0, 3.0, 1.0, -5.0, -6.0, -2.0 / 3.0),
        (1.5, 2.5, 4.0, -1.0, 3.75, 1.5 / 2.5),
        (100.0, 7.0, 107.0, 93.0, 700.0, 100.0 / 7.0),
    ]
    for a_v, b_v, exp_add, exp_sub, exp_mul, exp_div in cases:
        a32 = float32_t.as_const(a_v)
        b32 = float32_t.as_const(b_v)
        assert abs(float(a32 + b32) - exp_add) < 1e-4, f"float32 {a_v}+{b_v}"
        assert abs(float(a32 - b32) - exp_sub) < 1e-4, f"float32 {a_v}-{b_v}"
        assert abs(float(a32 * b32) - exp_mul) < 1e-3, f"float32 {a_v}*{b_v}"
        assert abs(float(a32 / b32) - exp_div) < 1e-4, f"float32 {a_v}/{b_v}"

        a64 = float64_t.as_const(a_v)
        b64 = float64_t.as_const(b_v)
        assert abs(float(a64 + b64) - exp_add) < 1e-9, f"float64 {a_v}+{b_v}"
        assert abs(float(a64 - b64) - exp_sub) < 1e-9, f"float64 {a_v}-{b_v}"
        assert abs(float(a64 * b64) - exp_mul) < 1e-9, f"float64 {a_v}*{b_v}"
        assert abs(float(a64 / b64) - exp_div) < 1e-9, f"float64 {a_v}/{b_v}"
    print("test_bare_operators_native_sim passed")


def test_conversions():
    for v in [1.5, -2.25, 0.0, 100.0, 0.001, 3.14159, -3.14159]:
        f32 = float32_t.as_const(v)
        f64 = sim_call(float32_to_float64, f32)
        assert abs(float(f64) - v) < 1e-6, f"f32_to_f64({v})"
        back = sim_call(float64_to_float32, f64)
        assert float(back) == float(f32), f"f64_to_f32(f32_to_f64({v})) roundtrip"

    for v in [3.7, -3.7, 0.0, 100.9, -100.9, 2147483.0]:
        n = sim_call(float64_to_int32, float64_t.as_const(v))
        assert int(n) == int(v), f"float64_to_int32({v})"

    for n in [3, -3, 0, 100, -100, 2147483, -2147483, 123456789]:
        f = sim_call(int32_to_float64, n)
        assert float(f) == float(n), f"int32_to_float64({n})"
    print("test_conversions passed")


def test_unregistered_operator_raises_clear_error():
    """A struct type with no registered operator must raise a clear
    TypeError, not fall through to NamedTuple's default tuple
    concatenation/repeat behavior for +/-/*/ (the bug the struct-dispatch
    fix replaces)."""

    @struct
    class no_ops_t(NamedTuple):
        x: int32_t

    a = no_ops_t(x=1)
    b = no_ops_t(x=2)
    try:
        a + b
        assert False, "expected TypeError for unregistered PLUS"
    except TypeError as e:
        assert "PLUS" in str(e)
    print("test_unregistered_operator_raises_clear_error passed")


if __name__ == "__main__":
    test_bare_operators_native_sim()
    test_conversions()
    test_unregistered_operator_raises_clear_error()
