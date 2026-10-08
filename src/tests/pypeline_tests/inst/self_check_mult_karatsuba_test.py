# pyright: reportInvalidTypeForm=none
"""Self-checking Karatsuba multipliers, native vs generated VHDL
(native_vs_vhdl_sim_tests.py, --comb).

Every product is compared against make_inferred_mult, the pinned built-in
`*`, which no registration below can replace:

  - a plain 130-bit `*` under a global register_mult_karatsuba_inferred_leaves()
    (in VHDL the threshold-34 hybrid; native sim's `*` is a Python product);
  - direct calls of the hybrid at 64 x 64 and unequal 37 x 20;
  - a soft (shift-and-add leaf) Karatsuba at 12 bits, threshold 4.

Operands are zero/maximal edge pairs for the first cycles, then an xorshift
sequence. Probes print match flags and the low 16 product bits.
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

from pypeline import MAIN, Reg, make_uint_t, sim_assert, sim_finish, sim_print, uint1_t, uint8_t, uint16_t

from operators.soft import register_mult_karatsuba_inferred_leaves
from operators.soft_mult import (
    make_inferred_mult,
    make_mult_karatsuba_inferred_leaves,
    make_soft_mult_karatsuba,
)

uint12_t = make_uint_t(12)
uint20_t = make_uint_t(20)
uint24_t = make_uint_t(24)
uint37_t = make_uint_t(37)
uint57_t = make_uint_t(57)
uint64_t = make_uint_t(64)
uint128_t = make_uint_t(128)
uint130_t = make_uint_t(130)
uint260_t = make_uint_t(260)

register_mult_karatsuba_inferred_leaves()

golden130 = make_inferred_mult(uint130_t, uint130_t)
hybrid64 = make_mult_karatsuba_inferred_leaves(uint64_t, uint64_t)
golden64 = make_inferred_mult(uint64_t, uint64_t)
hybrid_37x20 = make_mult_karatsuba_inferred_leaves(uint37_t, uint20_t)
golden_37x20 = make_inferred_mult(uint37_t, uint20_t)
soft12 = make_soft_mult_karatsuba(uint12_t, uint12_t, threshold=4)
golden12 = make_inferred_mult(uint12_t, uint12_t)

MAX130 = (1 << 130) - 1
NUM_CYCLES = 24


@MAIN
def self_check_mult_karatsuba():
    n: Reg[uint8_t]
    x: Reg[uint130_t] = 0x2C4F_9A31_77D0_E5B8_1F03_6C9D_42A8_B71E_5
    y: Reg[uint130_t] = 0x1B37_E0C2_95AF_4D68_0E91_C7F2_3A54_8B6D_9

    # Edge pairs first, then the xorshift sequence.
    a: uint130_t = x
    b: uint130_t = y
    if n == 0:
        a = 0
        b = MAX130
    elif n == 1:
        a = MAX130
        b = MAX130
    elif n == 2:
        a = MAX130
        b = 1
    elif n == 3:
        a = 1 << 129
        b = (1 << 65) - 1

    p130: uint260_t = a * b
    ok130: uint1_t = p130 == golden130(a, b)

    a64: uint64_t = a
    b64: uint64_t = b >> 66
    p64: uint128_t = hybrid64(a64, b64)
    ok64: uint1_t = p64 == golden64(a64, b64)

    a37: uint37_t = a >> 40
    b20: uint20_t = b >> 90
    p37: uint57_t = hybrid_37x20(a37, b20)
    ok37: uint1_t = p37 == golden_37x20(a37, b20)

    a12: uint12_t = a >> 100
    b12: uint12_t = b
    p12: uint24_t = soft12(a12, b12)
    ok12: uint1_t = p12 == golden12(a12, b12)

    sim_assert(ok130 & ok64 & ok37 & ok12, f"product mismatch at n={n}")
    # No debug print on the sim_finish() cycle (GHDL flush race).
    if n < NUM_CYCLES - 1:
        # 16-bit slices: VHDL sim_print formats through a 32-bit integer.
        lo130: uint16_t = p130
        lo64: uint16_t = p64
        lo37: uint16_t = p37
        lo12: uint16_t = p12
        sim_print(
            f"n={n} ok={ok130}{ok64}{ok37}{ok12} p130={lo130} p64={lo64} p37={lo37} p12={lo12}",
            debug=True,
        )
    if n == NUM_CYCLES - 1:
        sim_finish()

    x ^= x << 13
    x ^= x >> 7
    x ^= x << 17
    y ^= y << 11
    y ^= y >> 19
    y ^= y << 5
    n += 1
