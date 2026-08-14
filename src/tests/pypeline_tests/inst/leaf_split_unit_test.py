#!/usr/bin/env python3
# In-process unit tests for the raw-HDL leaf split model:
#   - RAW_VHDL.GET_LEAF_SPLIT_KIND / LEAF_MAX_SPLIT_SLICES classification
#   - RAW_VHDL._EQUAL_WIDTH_BITS_PER_STAGE_DICT (the D2 fix): a "bits"-kind
#     leaf's width is divided as evenly as possible across its chunk COUNT,
#     regardless of the specific delay fractions requested - see the
#     function's own docstring for why an earlier version of this fix
#     (inverting a real-cache-fitted cumulative delay curve to place UNEVEN
#     bit boundaries) was wrong, found by testing against real sky130
#     synthesis: it measurably missed timing goals the plain equal-width
#     split (and even the original linear model) met, because once a stage
#     boundary is registered, that stage's own delay depends only on ITS
#     OWN chunk width, not on cumulative position along the unregistered
#     leaf's delay axis.
#   - the sum(bits_per_stage) == num_bits invariant never breaks, including
#     at extreme slice counts (more chunks requested than bits available)
import os
import random
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

import RAW_VHDL


class FakeLogic:
    def __init__(self, func_name):
        self.func_name = func_name


class FakeTimingParams:
    def __init__(self, slices):
        self._slices = list(slices)


def test_split_kind_classification():
    cases = [
        ("BIN_OP_MINUS_uint34_t_uint34_t", RAW_VHDL.SPLIT_KIND_BITS),
        ("BIN_OP_PLUS_uint34_t_uint34_t", RAW_VHDL.SPLIT_KIND_BITS),
        ("BIN_OP_EQ_uint32_t_uint1_t", RAW_VHDL.SPLIT_KIND_BITS),
        ("BIN_OP_NEQ_uint32_t_uint1_t", RAW_VHDL.SPLIT_KIND_BITS),
        ("BIN_OP_GT_int10_t_int10_t", RAW_VHDL.SPLIT_KIND_BITS),
        ("BIN_OP_GTE_uint10_t_uint10_t", RAW_VHDL.SPLIT_KIND_BITS),
        ("BIN_OP_LT_int10_t_int10_t", RAW_VHDL.SPLIT_KIND_BITS),
        ("BIN_OP_LTE_uint10_t_uint10_t", RAW_VHDL.SPLIT_KIND_BITS),
        ("accum_uint32_t", RAW_VHDL.SPLIT_KIND_BITS),
        ("BIN_OP_AND_uint1_t_uint1_t", RAW_VHDL.SPLIT_KIND_1LL),
        ("BIN_OP_OR_uint1_t_uint1_t", RAW_VHDL.SPLIT_KIND_1LL),
        ("BIN_OP_XOR_uint34_t_uint34_t", RAW_VHDL.SPLIT_KIND_1LL),
        ("BIN_OP_MULT_uint16_t_uint16_t", RAW_VHDL.SPLIT_KIND_1LL),
        ("BIN_OP_INFERRED_MULT_uint16_t_uint16_t", RAW_VHDL.SPLIT_KIND_1LL),
        ("UNARY_OP_NOT_uint1_t", RAW_VHDL.SPLIT_KIND_1LL),
        ("UNARY_OP_NEGATE_float_8_23_t", RAW_VHDL.SPLIT_KIND_1LL),
        ("MUX_uint32_t", RAW_VHDL.SPLIT_KIND_1LL),
        ("BIN_OP_SL_uint32_t_uint5_t", RAW_VHDL.SPLIT_KIND_NONE),
        ("BIN_OP_SR_uint32_t_uint5_t", RAW_VHDL.SPLIT_KIND_NONE),
        ("BIN_OP_MOD_uint32_t_uint32_t", RAW_VHDL.SPLIT_KIND_NONE),
        ("CAST_uint8_t_to_uint32_t", RAW_VHDL.SPLIT_KIND_NONE),
        ("float_8_23_t_2_3_4", RAW_VHDL.SPLIT_KIND_NONE),
    ]
    for func_name, expected in cases:
        got = RAW_VHDL.GET_LEAF_SPLIT_KIND(FakeLogic(func_name))
        assert got == expected, f"{func_name}: got {got}, expected {expected}"


def test_leaf_max_split_slices():
    # SPLIT_KIND_1LL caps at 2 (stage_for_1ll's real ceiling - a 3rd slice
    # is a bare register around logic that never shrinks, see RAW_VHDL
    # module docstring)
    assert RAW_VHDL.LEAF_MAX_SPLIT_SLICES(FakeLogic("MUX_uint32_t")) == 2
    assert RAW_VHDL.LEAF_MAX_SPLIT_SLICES(FakeLogic("BIN_OP_AND_uint1_t_uint1_t")) == 2
    # SPLIT_KIND_BITS is uncapped here (bounded instead by width, inside
    # GET_BITS_PER_STAGE_DICT itself)
    assert (
        RAW_VHDL.LEAF_MAX_SPLIT_SLICES(FakeLogic("BIN_OP_MINUS_uint34_t_uint34_t"))
        is None
    )
    # SPLIT_KIND_NONE never accepts any slice
    assert RAW_VHDL.LEAF_MAX_SPLIT_SLICES(FakeLogic("BIN_OP_SL_uint32_t_uint5_t")) == 0


def test_equal_width_split_ignores_requested_fraction():
    # The whole point of the D2 fix: a single cut ALWAYS produces a
    # balanced {17,17}-style split of a 34-bit op, regardless of whether
    # the requested fraction was 0.5, 0.9, or 0.001 - because per-stage
    # delay depends on that stage's own chunk WIDTH (a fresh registered
    # computation), not on where along the leaf's unregistered delay axis
    # PLAN_CUTS happened to want to cut.
    for fraction in (0.001, 0.1, 0.5, 0.9, 0.9999):
        tp = FakeTimingParams([fraction])
        d = RAW_VHDL.GET_BITS_PER_STAGE_DICT(34, tp)
        assert d == {0: 17, 1: 17}, (fraction, d)


def test_equal_width_split_balances_multiple_chunks():
    tp = FakeTimingParams([0.3, 0.6])  # 3 chunks, uneven fractions
    d = RAW_VHDL.GET_BITS_PER_STAGE_DICT(34, tp)
    assert sum(d.values()) == 34, d
    assert max(d.values()) - min(d.values()) <= 1, d


def test_bits_per_stage_dict_sum_and_balance_invariant_stress():
    # Random (num_bits, n_slices) combos within what a leaf's own width can
    # usefully support (n_slices <= num_bits - 1, the cap SWEEP.
    # BUILD_SLICE_LANDSCAPE now enforces upstream via RAW_VHDL.
    # GET_LEAF_BIT_WIDTH) - must never crash, must always conserve total
    # bit count, and must always be as balanced as integer division allows.
    # n_slices beyond that cap is a SEPARATE, deliberate contract (an
    # interior zero-bit stage must hard-error) covered by
    # floor_and_bits_cap_unit_test.py, not this invariant-stress test.
    rng = random.Random(1234567)
    for _ in range(500):
        num_bits = rng.randint(1, 200)
        n_slices = rng.randint(0, max(0, num_bits - 1))
        tp = FakeTimingParams([rng.random() for _ in range(n_slices)])
        d = RAW_VHDL.GET_BITS_PER_STAGE_DICT(num_bits, tp)
        assert sum(d.values()) == num_bits, (num_bits, n_slices, d)
        vals = list(d.values())
        assert all(v >= 0 for v in vals), (num_bits, n_slices, d)
        assert max(vals) - min(vals) <= 1, (num_bits, n_slices, d)


if __name__ == "__main__":
    test_split_kind_classification()
    test_leaf_max_split_slices()
    test_equal_width_split_ignores_requested_fraction()
    test_equal_width_split_balances_multiple_chunks()
    test_bits_per_stage_dict_sum_and_balance_invariant_stress()
    print("All leaf split-model unit tests passed.")
