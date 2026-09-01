#!/usr/bin/env python3
# In-process unit tests for three bugs found (but not originally fixed)
# during this session's audit of the autopipelining slice-placement work:
#
#   - SWEEP.AT_PREDICTED_FLOOR (3a): the floor-stop check used to have no
#     upper bound - curr_mhz >= tolerance*floor was satisfied by ANY fmax
#     above the floor, however far above. Seen for real: a sweep stopped at
#     124.18 MHz citing a ~71.6 MHz predicted floor (73% above it, nowhere
#     near stagnating) and reported TIMING NOT MET despite comfortably
#     beating its own 147 MHz goal. Fixed with a symmetric tolerance band.
#   - SWEEP.BEST_SNAPSHOT_MET_ALL_GOALS (3b): restoring best_tpl (the best
#     iteration seen) never re-checked whether that snapshot actually met
#     its goal before writing it out - a build could restore a snapshot
#     that measured 244.72 MHz against a 147.00 MHz target and still exit
#     TIMING NOT MET, because met_timing was last written by a later,
#     worse iteration (e.g. one a floor-stop landed on afterward).
#   - RAW_VHDL.GET_LEAF_BIT_WIDTH + SWEEP's SLICEABLE legal-unit cap (3c):
#     a narrow "bits"-kind leaf used to accept far more cuts than its own
#     width could usefully support (a 4-bit op with 15 legal units accepted
#     14 cuts), producing interior zero-bit stages - bare registers around
#     no logic. Fixed by capping legal units to width-1 in
#     SWEEP.SliceLandscape.finalize(), backstopped by a hard error in
#     RAW_VHDL.GET_BITS_PER_STAGE_DICT if one ever slips through anyway.
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

import RAW_VHDL
import SWEEP


# ─── 3a: AT_PREDICTED_FLOOR ──────────────────────────────────────────────


def test_far_above_floor_is_not_at_floor():
    # The exact real-world case: 124.18 MHz achieved, ~71.6 MHz predicted
    # floor, 147.0 MHz goal. 73% above the floor - must NOT count as "at
    # the floor".
    assert not SWEEP.AT_PREDICTED_FLOOR(124.18, 71.6, 147.0)


def test_near_floor_from_above_is_at_floor():
    # Genuinely stagnated just above the floor (within FLOOR_TOLERANCE).
    floor = 100.0
    curr = floor * SWEEP.FLOOR_TOLERANCE  # exactly at the lower edge
    assert SWEEP.AT_PREDICTED_FLOOR(curr, floor, 200.0)
    assert SWEEP.AT_PREDICTED_FLOOR(floor, floor, 200.0)  # exactly at floor


def test_below_floor_is_not_at_floor():
    assert not SWEEP.AT_PREDICTED_FLOOR(50.0, 100.0, 200.0)


def test_floor_above_target_never_triggers():
    # A floor above the goal isn't a reason to stop, regardless of curr_mhz.
    assert not SWEEP.AT_PREDICTED_FLOOR(150.0, 150.0, 100.0)


def test_none_floor_never_triggers():
    assert not SWEEP.AT_PREDICTED_FLOOR(100.0, None, 200.0)


def test_at_predicted_floor_stress_symmetry():
    # For any floor < target, curr_mhz must be accepted iff it falls in the
    # closed band [tolerance*floor, floor/tolerance].
    import random

    rng = random.Random(99)
    for _ in range(300):
        floor = rng.uniform(1.0, 500.0)
        target = floor + rng.uniform(0.01, 500.0)
        curr = rng.uniform(0.0, 1000.0)
        got = SWEEP.AT_PREDICTED_FLOOR(curr, floor, target)
        expected = (
            curr >= SWEEP.FLOOR_TOLERANCE * floor
            and curr <= floor / SWEEP.FLOOR_TOLERANCE
        )
        assert got == expected, (curr, floor, target, got, expected)


# ─── 3b: BEST_SNAPSHOT_MET_ALL_GOALS ─────────────────────────────────────


def test_best_score_above_one_met_all_goals():
    # The exact real-world case: 244.72 MHz achieved vs 147.00 MHz target
    # -> score 1.664..., comfortably >= 1.0.
    assert SWEEP.BEST_SNAPSHOT_MET_ALL_GOALS(244.72 / 147.00)


def test_best_score_exactly_one_met_all_goals():
    assert SWEEP.BEST_SNAPSHOT_MET_ALL_GOALS(1.0)


def test_best_score_below_one_did_not_meet():
    assert not SWEEP.BEST_SNAPSHOT_MET_ALL_GOALS(0.999)


def test_best_score_none_did_not_meet():
    assert not SWEEP.BEST_SNAPSHOT_MET_ALL_GOALS(None)


# ─── 3c: leaf bit-width cap on legal SLICEABLE units ─────────────────────


class FakeLogic:
    def __init__(self, func_name, inputs, outputs, wire_to_c_type):
        self.func_name = func_name
        self.inputs = inputs
        self.outputs = outputs
        self.wire_to_c_type = wire_to_c_type


def test_get_leaf_bit_width_uses_widest_wire():
    logic = FakeLogic(
        "BIN_OP_MINUS_uint34_t_uint34_t",
        inputs=["left", "right"],
        outputs=["out"],
        wire_to_c_type={"left": "uint34_t", "right": "uint10_t", "out": "uint1_t"},
    )
    assert RAW_VHDL.GET_LEAF_BIT_WIDTH(logic, None) == 34


def test_get_leaf_bit_width_uses_binary_inputs_not_carry_output():
    logic = FakeLogic(
        "BIN_OP_PLUS_uint2_t_uint2_t",
        inputs=["left", "right"],
        outputs=["out"],
        wire_to_c_type={"left": "uint2_t", "right": "uint2_t", "out": "uint3_t"},
    )
    assert RAW_VHDL.GET_LEAF_BIT_WIDTH(logic, None) == 2


def test_get_leaf_bit_width_none_when_no_types_resolve():
    logic = FakeLogic("mystery", inputs=["x"], outputs=[], wire_to_c_type={})
    assert RAW_VHDL.GET_LEAF_BIT_WIDTH(logic, None) is None


def _landscape_with_one_sliceable_segment(span_units, max_legal_units):
    landscape = SWEEP.SliceLandscape("synthetic", span_units, 1.0)
    seg = SWEEP.Segment(
        "leaf", "BIN_OP_MINUS", 0.0, float(span_units), SWEEP.Segment.SLICEABLE
    )
    seg.max_legal_units = max_legal_units
    landscape.segments.append(seg)
    landscape.finalize({})
    return landscape


def test_narrow_leaf_caps_internal_units_to_width_minus_one():
    # The plan's own documented bad case: a 4-bit op spread over 15 units
    # used to offer all 15 as internal sites. It now exposes exactly three
    # nonempty bit-internal sites plus the distinct operation-output boundary.
    landscape = _landscape_with_one_sliceable_segment(15, max_legal_units=4)
    legal_count = sum(1 for l in landscape.legal if l)
    assert legal_count == 4, legal_count
    internal_count = sum(
        isinstance(p, SWEEP.BitPlacementRequest) for p in landscape.candidates
    )
    assert internal_count == 3, internal_count


def test_two_bit_leaf_keeps_one_internal_and_one_output_boundary():
    landscape = _landscape_with_one_sliceable_segment(14, max_legal_units=2)
    kinds = [p.kind for p in landscape.candidates]
    assert kinds.count(SWEEP.PipelinePlacement.BIT_INTERNAL) == 1, kinds
    assert kinds.count(SWEEP.PipelinePlacement.INSTANCE_OUTPUT) == 1, kinds


def test_wide_leaf_uncapped_when_width_exceeds_span():
    # A 64-bit op over only 10 units: the cap (63) exceeds the span, so
    # every unit stays legal exactly like before this fix.
    landscape = _landscape_with_one_sliceable_segment(10, max_legal_units=64)
    legal_count = sum(1 for l in landscape.legal if l)
    assert legal_count == 10, legal_count


def test_unknown_width_exposes_only_truthful_output_boundary():
    # Without a resolved width, no internal raster position can be mapped to
    # the equal-width bit boundary raw VHDL will emit. Keep the concrete
    # operation-output boundary, but do not fabricate internal placements.
    landscape = _landscape_with_one_sliceable_segment(15, max_legal_units=None)
    legal_count = sum(1 for l in landscape.legal if l)
    assert legal_count == 1, legal_count
    assert all(
        p.kind == SWEEP.PipelinePlacement.INSTANCE_OUTPUT
        for p in landscape.candidates
    )


def test_bits_per_stage_dict_rejects_interior_zero_bit_stage():
    class FakeTimingParams:
        def __init__(self, slices):
            self._slices = list(slices)

    # 14 slices (15 chunks) on a 4-bit op is exactly the documented bad
    # case ([0,1,0,0,0,1,0,0,0,1,0,0,0,1,0]) - must now raise.
    tp = FakeTimingParams([i / 15.0 for i in range(1, 15)])
    try:
        RAW_VHDL.GET_BITS_PER_STAGE_DICT(4, tp)
        assert False, "expected an Exception for an interior zero-bit stage"
    except Exception as e:
        assert "interior zero-bit stage" in str(e), e


def test_bits_per_stage_dict_allows_leading_trailing_zero_bit_stage():
    class FakeTimingParams:
        def __init__(self, slices):
            self._slices = list(slices)

    # 1 bit split into 2 chunks: one stage is necessarily 0 bits, but it's
    # a boundary (leading/trailing) stage, not interior - must not raise.
    tp = FakeTimingParams([0.5])
    d = RAW_VHDL.GET_BITS_PER_STAGE_DICT(1, tp)
    assert sum(d.values()) == 1, d


def test_bits_per_stage_dict_within_cap_never_raises():
    # Landscape's own cap (width-1 legal units) should keep every request
    # it actually produces safely under the hard-error threshold.
    for num_bits in range(1, 40):
        class FakeTimingParams:
            def __init__(self, slices):
                self._slices = list(slices)

        max_slices = max(0, num_bits - 1)
        tp = FakeTimingParams([(i + 1) / (max_slices + 1.0) for i in range(max_slices)])
        d = RAW_VHDL.GET_BITS_PER_STAGE_DICT(num_bits, tp)  # must not raise
        assert sum(d.values()) == num_bits


if __name__ == "__main__":
    test_far_above_floor_is_not_at_floor()
    test_near_floor_from_above_is_at_floor()
    test_below_floor_is_not_at_floor()
    test_floor_above_target_never_triggers()
    test_none_floor_never_triggers()
    test_at_predicted_floor_stress_symmetry()
    test_best_score_above_one_met_all_goals()
    test_best_score_exactly_one_met_all_goals()
    test_best_score_below_one_did_not_meet()
    test_best_score_none_did_not_meet()
    test_get_leaf_bit_width_uses_widest_wire()
    test_get_leaf_bit_width_none_when_no_types_resolve()
    test_get_leaf_bit_width_uses_binary_inputs_not_carry_output()
    test_narrow_leaf_caps_internal_units_to_width_minus_one()
    test_two_bit_leaf_keeps_one_internal_and_one_output_boundary()
    test_wide_leaf_uncapped_when_width_exceeds_span()
    test_unknown_width_exposes_only_truthful_output_boundary()
    test_bits_per_stage_dict_rejects_interior_zero_bit_stage()
    test_bits_per_stage_dict_allows_leading_trailing_zero_bit_stage()
    test_bits_per_stage_dict_within_cap_never_raises()
    print("All floor-tolerance/best-snapshot/bits-cap unit tests passed.")
