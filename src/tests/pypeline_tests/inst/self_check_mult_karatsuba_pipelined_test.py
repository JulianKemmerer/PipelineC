# pyright: reportInvalidTypeForm=none
"""Pipelined Karatsuba with inferred leaves, native vs real sliced VHDL
(native_vs_vhdl_sim_tests.py, non---comb, sky130).

A pure @MAIN(MHz) computes a 16 x 16 make_mult_karatsuba_inferred_leaves
product (threshold 6: two Karatsuba levels over 4-6-bit inferred leaves,
small enough for a quick sky130 sweep) and the sweep slices it. The operands
travel with the product, so the stateful checker MAIN compares each output
against make_inferred_mult without knowing the pipeline depth. It learns
that depth from the first valid output and then asserts seq continuity, as
native_vs_vhdl_pipelined_main_test.py does; probes are valid-gated.
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

from pypeline import (
    MAIN, NamedTuple, Reg, Wire, sim_assert, sim_finish, sim_print, struct,
    uint1_t, uint16_t, uint32_t,
)

from operators.soft_mult import make_inferred_mult, make_mult_karatsuba_inferred_leaves

hybrid16 = make_mult_karatsuba_inferred_leaves(uint16_t, uint16_t, threshold=6)
golden16 = make_inferred_mult(uint16_t, uint16_t)


@struct
class kp_t(NamedTuple):
    a: uint16_t
    b: uint16_t
    p: uint32_t
    seq: uint16_t
    valid: uint1_t


kp_in: Wire[kp_t]
kp_out: Wire[kp_t]


# Pure comb MAIN: one output wire carrying product, operands, seq and valid,
# so every field leaves the pipeline at the same depth.
@MAIN(150.0)
def karatsuba_pipe():
    v: kp_t = kp_in
    o: kp_t = v
    o.p = hybrid16(v.a, v.b)
    kp_out = o


NUM_CHECK = 30
MAX_CYCLES = 200


@MAIN
def karatsuba_checker() -> kp_t:
    count: Reg[uint16_t]
    seen: Reg[uint16_t]
    lat_reg: Reg[uint16_t]
    done: Reg[uint1_t]
    x: Reg[uint32_t] = 0x9E3779B9
    if done:
        sim_finish()

    i: kp_t
    i.valid = 1
    i.seq = count
    i.a = x
    i.b = x >> 16
    # Zero and maximal operands among the first samples.
    if count == 0:
        i.a = 0
        i.b = 0xFFFF
    elif count == 1:
        i.a = 0xFFFF
        i.b = 0xFFFF
    kp_in = i

    ov: kp_t = kp_out
    if ov.valid & ~done:
        if seen == 0:
            lat_reg = count - ov.seq
            sim_print(f"first out at count={count} seq={ov.seq}", debug=True)
        else:
            sim_assert(
                ov.seq == count - lat_reg,
                f"seq gap: count={count} seq={ov.seq} lat={lat_reg}",
            )
        sim_assert(ov.p == golden16(ov.a, ov.b), f"product mismatch seq={ov.seq}")
        lo: uint16_t = ov.p
        hi: uint16_t = ov.p >> 16
        sim_print(f"seq={ov.seq} p_hi={hi} p_lo={lo}", debug=True)
        if seen == NUM_CHECK - 1:
            done = 1
        seen += 1

    sim_assert(
        count < MAX_CYCLES,
        f"no/too-few outputs within {MAX_CYCLES} cycles: seen={seen}",
    )
    x ^= x << 13
    x ^= x >> 17
    x ^= x << 5
    count += 1
    return ov
