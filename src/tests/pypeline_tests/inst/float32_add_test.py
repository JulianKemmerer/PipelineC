# pyright: reportInvalidTypeForm=none
import sys, os

# Path for pypeline import
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)
from pypeline import (
    MAIN,
    uint6_t,
    uint32_t,
    int32_t,
    int33_t,
    register_unary_operator,
    concat,
    sim_call,
)

# Path for pypeline_tests import
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "def")
)
import pypeline_tests


@MAIN
def uint_negate_test(a: uint32_t) -> int33_t:
    return -a


@MAIN
def int_negate_test(a: int32_t) -> int33_t:
    return -a


register_unary_operator("NEGATE", int32_t, pypeline_tests.negate_int32)
register_unary_operator("NEGATE", uint32_t, pypeline_tests.negate_uint32)


@MAIN
def abs_int32_test(a: int32_t) -> uint32_t:
    return pypeline_tests.abs_int32(a)


@MAIN
def shift_var(v: uint32_t, amount: uint6_t) -> uint32_t:
    return v << amount


@MAIN
def shift_var_right(v: uint32_t, amount: uint6_t) -> uint32_t:
    return v >> amount


@MAIN
def clz_uint32_test(a: uint32_t) -> uint6_t:
    return pypeline_tests.clz_uint32(a)


@MAIN
def float32_const_init() -> pypeline_tests.float32_t:
    x: pypeline_tests.float32_t = pypeline_tests.float32_t.as_const(1.5)
    return x


@MAIN
def float32_const_neg() -> pypeline_tests.float32_t:
    x: pypeline_tests.float32_t = pypeline_tests.float32_t.as_const(-1.0)
    return x


@MAIN
def float_add_32_main(left_as_u32: uint32_t, right_as_u32: uint32_t) -> uint32_t:
    # Un/pack float32_t from uint32_t bit representation (mostly for sim/top level ports)
    E_LEN = len(pypeline_tests.float32_t.typeof("exp"))
    M_LEN = len(pypeline_tests.float32_t.typeof("man"))
    M_SLICE = slice(M_LEN - 1, 0)
    E_SLICE = slice(E_LEN + M_LEN - 1, M_LEN)
    S_BIT = E_LEN + M_LEN
    left: pypeline_tests.float32_t = pypeline_tests.float32_t(
        sign=left_as_u32[S_BIT],
        man=left_as_u32[M_SLICE],
        exp=left_as_u32[E_SLICE],
    )
    right: pypeline_tests.float32_t = pypeline_tests.float32_t(
        sign=right_as_u32[S_BIT],
        man=right_as_u32[M_SLICE],
        exp=right_as_u32[E_SLICE],
    )
    result: pypeline_tests.float32_t = left + right
    result_as_u32: uint32_t = concat(result.sign, result.exp, result.man)
    return result_as_u32


def test_float_add_32():
    import struct as _struct

    def py_to_float32(f):
        bits = _struct.unpack(">I", _struct.pack(">f", float(f)))[0]
        return pypeline_tests.float32_t(
            sign=(bits >> 31) & 1,
            exp=(bits >> 23) & 0xFF,
            man=bits & 0x7FFFFF,
        )

    def float32_to_py(r):
        bits = (int(r.sign) << 31) | (int(r.exp) << 23) | int(r.man)
        return _struct.unpack(">f", _struct.pack(">I", bits))[0]

    cases = [
        (1.0, 2.0, 3.0),
        (0.0, 0.0, 0.0),
        (-1.0, 2.0, 1.0),
        (1.5, 2.5, 4.0),
        (-2.0, -2.0, -4.0),
        (0.5, 0.5, 1.0),
    ]
    for a, b, expected in cases:
        result = sim_call(
            pypeline_tests.float_add_32, py_to_float32(a), py_to_float32(b)
        )
        got = float32_to_py(result)
        assert got == expected, f"{a} + {b} = {got}, expected {expected}"
    print("test_float_add_32 passed")


if __name__ == "__main__":
    test_float_add_32()
