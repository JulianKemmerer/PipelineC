import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

from typing import NamedTuple

from pypeline import MAIN, int4_t, sim_call, sim_reset, struct, uint4_t, uint8_t


@struct
class p_t(NamedTuple):
    c: uint4_t


@struct
class q_t(NamedTuple):
    c: int4_t


@struct
class r_t(NamedTuple):
    c: uint8_t


@MAIN
def ctor_unsigned(a: p_t) -> p_t:
    """Repro: constructor kwarg must narrow identically to field assignment."""
    return p_t(c=a.c + 1)


@MAIN
def assign_unsigned(a: p_t) -> p_t:
    o: p_t
    o.c = a.c + 1
    return o


@MAIN
def ctor_signed(a: q_t) -> q_t:
    return q_t(c=a.c + 1)


@MAIN
def ctor_byte(a: r_t) -> r_t:
    return r_t(c=a.c + 1)


def test_struct_ctor_narrows_unsigned_overflow():
    """p_t(c=a.c+1) at uint4_t max (15) must wrap to 0, matching o.c = a.c+1."""
    sim_reset()
    a = p_t(c=15)
    r_ctor = sim_call(ctor_unsigned, a)
    assert int(r_ctor.c) == 0, f"ctor expected 0, got {int(r_ctor.c)}"

    sim_reset()
    r_assign = sim_call(assign_unsigned, a)
    assert int(r_assign.c) == 0, f"assignment expected 0, got {int(r_assign.c)}"
    print("test_struct_ctor_narrows_unsigned_overflow PASS")


def test_struct_ctor_narrows_signed_overflow():
    """q_t(c=a.c+1) at int4_t max (7) must wrap to -8 (sign-extend), not 8."""
    sim_reset()
    a = q_t(c=7)
    r = sim_call(ctor_signed, a)
    assert int(r.c) == -8, f"expected -8, got {int(r.c)}"
    print("test_struct_ctor_narrows_signed_overflow PASS")


def test_struct_ctor_narrows_byte_boundary():
    """r_t(c=a.c+1) at uint8_t max (255) must wrap to 0."""
    sim_reset()
    a = r_t(c=255)
    r = sim_call(ctor_byte, a)
    assert int(r.c) == 0, f"expected 0, got {int(r.c)}"
    print("test_struct_ctor_narrows_byte_boundary PASS")


if __name__ == "__main__":
    test_struct_ctor_narrows_unsigned_overflow()
    test_struct_ctor_narrows_signed_overflow()
    test_struct_ctor_narrows_byte_boundary()
    print("All struct_ctor_narrow tests passed.")
