# pyright: reportInvalidTypeForm=none
"""Fixture for soft_mult_karatsuba_leaves_test.py: Karatsuba leaf policies
under different INFERRED_MULT registrations. -D CASE=<name> selects the
registrations, since they are process-global, and the width of
plain_mult_main's `*` (the only MAIN that reaches the registry):

  global130      register_mult_karatsuba_inferred_leaves(); 130-bit `*`
  direct         no registration
  exact_soft     register_soft_mult() plus an exact uint34 soft registration
                 at a hybrid leaf width (checked through exact_soft_main)
  soft_default   register_soft_mult_karatsuba(); 24-bit `*`

The other MAINs call factories directly and are the same in every case.
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
        "..", "..", "..", "..", "include", "pypeline",
    ),
)

from pypeline import MAIN, make_uint_t, param, register_operator

from operators.soft import (
    register_mult_karatsuba_inferred_leaves,
    register_soft_mult,
    register_soft_mult_karatsuba,
)
from operators.soft_mult import (
    make_mult_karatsuba_inferred_leaves,
    make_soft_mult_carry_save,
    make_soft_mult_karatsuba,
)

CASE = param("CASE", "global130", choices=("global130", "direct", "exact_soft", "soft_default"))

uint20_t = make_uint_t(20)
uint24_t = make_uint_t(24)
uint34_t = make_uint_t(34)
uint37_t = make_uint_t(37)
uint40_t = make_uint_t(40)
uint64_t = make_uint_t(64)
uint130_t = make_uint_t(130)
uint48_t = make_uint_t(48)
uint57_t = make_uint_t(57)
uint80_t = make_uint_t(80)
uint128_t = make_uint_t(128)
uint260_t = make_uint_t(260)

if CASE == "global130":
    register_mult_karatsuba_inferred_leaves()
elif CASE == "exact_soft":
    register_soft_mult()
    register_operator(
        "INFERRED_MULT", uint34_t, uint34_t, make_soft_mult_carry_save(uint34_t, uint34_t)
    )
elif CASE == "soft_default":
    register_soft_mult_karatsuba()

PLAIN_BITS = {"global130": 130, "soft_default": 24}.get(CASE, 8)
plain_in_t = make_uint_t(PLAIN_BITS)
plain_out_t = make_uint_t(2 * PLAIN_BITS)


@MAIN
def plain_mult_main(a: plain_in_t, b: plain_in_t) -> plain_out_t:
    return a * b


hybrid64 = make_mult_karatsuba_inferred_leaves(uint64_t, uint64_t)
hybrid_37x20 = make_mult_karatsuba_inferred_leaves(uint37_t, uint20_t)
hybrid40 = make_mult_karatsuba_inferred_leaves(uint40_t, uint40_t, threshold=16)
soft40 = make_soft_mult_karatsuba(uint40_t, uint40_t)
soft40_t24 = make_soft_mult_karatsuba(uint40_t, uint40_t, threshold=24)
hybrid130 = make_mult_karatsuba_inferred_leaves(uint130_t, uint130_t)


@MAIN
def hybrid64_main(a: uint64_t, b: uint64_t) -> uint128_t:
    return hybrid64(a, b)


@MAIN
def hybrid_37x20_main(a: uint37_t, b: uint20_t) -> uint57_t:
    return hybrid_37x20(a, b)


# Three configurations of the same 40-bit Karatsuba in one design: each must
# be its own entity.
@MAIN
def hybrid40_main(a: uint40_t, b: uint40_t) -> uint80_t:
    return hybrid40(a, b)


@MAIN
def soft40_main(a: uint40_t, b: uint40_t) -> uint80_t:
    return soft40(a, b)


@MAIN
def soft40_t24_main(a: uint40_t, b: uint40_t) -> uint80_t:
    return soft40_t24(a, b)


@MAIN
def exact_soft_main(a: uint130_t, b: uint130_t) -> uint260_t:
    return hybrid130(a, b)
