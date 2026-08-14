#!/usr/bin/env python3
# In-process unit tests for SWEEP.PLAN_CUTS's boundary-snap behavior: when
# the per-stage budget fills strictly inside a wide SLICEABLE ("bits") leaf,
# the walk should prefer waiting (within a bounded budget overrun) for the
# end of the run of small segments that follows - not the nearest segment
# edge, the end of the whole run (SWEEP._RUN_BOUNDARY_UNITS) - over cutting
# immediately mid-segment or stopping at the first tiny edge in that run.
#
# Found necessary by testing the real divider design (a serial chain of
# repeated [MINUS][NOT][MUX] loop iterations) against real sky130 synthesis:
#   - with no snap at all, a low cut count merged an entire loop iteration's
#     tail, the NOT+MUX between iterations, and the next iteration's head
#     into one ~11.4ns stage (reported critical path: Start reg .../for_i_1_
#     bin_op_minus/... End reg .../for_i_0_bin_op_minus/...), on a design
#     whose reference (real sky130 OpenSTA) shape is ~6.96ns for one whole,
#     unsliced iteration.
#   - snapping to the NEAREST boundary regressed further (a mid-run boundary
#     like MINUS-end/NOT-start is nearly free to reach but does nothing to
#     protect the next iteration, since NOT+MUX+next-MINUS still merge).
#   - snapping to the FARTHEST boundary within a large flat tolerance
#     overshot the other way, sometimes skipping a whole extra iteration.
#   - only snapping to the end of the small-segment RUN (independent of any
#     tolerance tuning for how many small segments happen to be in it) gets
#     this right in all three regimes.
import os
import random
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

import SWEEP

MINUS_NS = 3.851  # this design's real cached BIN_OP_MINUS_uint34_t_uint34_t
NOT_NS = 0.815  # this design's real cached UNARY_OP_NOT_uint1_t
MUX_NS = 3.268  # this design's real cached MUX_uint32_t
STEP_NS = MINUS_NS + NOT_NS + MUX_NS
UNITS_TO_NS = 0.1


def _build_repeated_step_landscape(n_steps):
    """n_steps repeated [SLICEABLE MINUS][SLICEABLE_1LL NOT][SLICEABLE_1LL
    MUX] triples in series, matching the real baseline divider's shape
    (diff1 = rem_ext - d1; q1 = ~diff1[33]; remainder = mux(diff1, rem_ext))."""
    total_units = int(round(n_steps * STEP_NS / UNITS_TO_NS))
    landscape = SWEEP.SliceLandscape("synthetic", total_units, UNITS_TO_NS)
    pos = 0.0
    for i in range(n_steps):
        minus_end = pos + MINUS_NS / UNITS_TO_NS
        landscape.segments.append(
            SWEEP.Segment(
                f"step{i}/MINUS", "BIN_OP_MINUS", pos, minus_end, SWEEP.Segment.SLICEABLE
            )
        )
        not_end = minus_end + NOT_NS / UNITS_TO_NS
        landscape.segments.append(
            SWEEP.Segment(
                f"step{i}/NOT", "UNARY_OP_NOT", minus_end, not_end, SWEEP.Segment.SLICEABLE_1LL
            )
        )
        mux_end = not_end + MUX_NS / UNITS_TO_NS
        landscape.segments.append(
            SWEEP.Segment(
                f"step{i}/MUX", "MUX", not_end, mux_end, SWEEP.Segment.SLICEABLE_1LL
            )
        )
        pos = mux_end
    landscape.finalize({})
    return landscape


def _stage_ns_list(landscape, cuts):
    n = landscape.total_units
    bounds = [-1] + list(cuts) + [n - 1]
    stages = []
    for i in range(len(bounds) - 1):
        w = sum(landscape.weight[u] for u in range(bounds[i] + 1, bounds[i + 1] + 1))
        stages.append(w * landscape.units_to_ns)
    return stages


def test_low_cut_density_never_merges_two_full_steps():
    # The exact real-world scenario that produced an ~11.4ns merged stage
    # before this fix: a 32-step subtree, first-guess cut count below one
    # cut per step. No stage may exceed roughly one step's own delay - not
    # 2+ steps worth.
    landscape = _build_repeated_step_landscape(32)
    total_ns = 32 * STEP_NS
    for denom in (33, 40):  # both real first-guess cut counts seen
        cuts = SWEEP.PLAN_CUTS(landscape, (total_ns / denom) / UNITS_TO_NS)
        stages = _stage_ns_list(landscape, cuts)
        worst = max(stages)
        max_allowed = STEP_NS * 1.15  # rounding/edge-of-subtree slack only
        assert worst <= max_allowed, (
            f"denom={denom}: worst stage {worst:.2f}ns exceeds {max_allowed:.2f}ns "
            f"(~{worst / STEP_NS:.2f} steps merged) - boundary snap regressed"
        )


def test_cuts_land_at_end_of_run_not_mid_run():
    # A cut must never land mid-run (e.g. MINUS-end/NOT-start, or NOT-end/
    # MUX-start) - only near the end of the whole [MINUS][NOT][MUX] run,
    # where the next repetition begins. Tolerance is intentionally loose
    # (a fraction of one step's own unit width, not a fixed unit count):
    # STEP_NS/UNITS_TO_NS is not an integer, so the walk's integer-unit
    # accumulation and _RUN_BOUNDARY_UNITS' own per-segment ceil() both
    # quantize independently and can drift apart by a few units over many
    # repetitions - real, harmless grid quantization, not a functional gap
    # (a cut landing MID-RUN, e.g. within NOT or MINUS, would be off by
    # tens of units - an order of magnitude more than this drift).
    landscape = _build_repeated_step_landscape(8)
    cuts = SWEEP.PLAN_CUTS(landscape, STEP_NS / UNITS_TO_NS)
    run_end_units = set(SWEEP._RUN_BOUNDARY_UNITS(landscape))
    tolerance = max(2, int(0.1 * STEP_NS / UNITS_TO_NS))
    off_run_end = [
        c for c in cuts if min(abs(c - b) for b in run_end_units) > tolerance
    ]
    assert not off_run_end, (cuts, sorted(run_end_units), tolerance)
    assert len(cuts) >= 6, cuts  # ~1 per step boundary across 8 steps


def test_plan_cuts_boundary_snap_invariants_stress():
    rng = random.Random(4242)
    for _ in range(300):
        n_steps = rng.randint(1, 50)
        landscape = _build_repeated_step_landscape(n_steps)
        n = landscape.total_units
        budget_units = rng.uniform(0.5, n)
        cuts = SWEEP.PLAN_CUTS(landscape, budget_units)
        assert cuts == sorted(set(cuts)), (n_steps, budget_units, cuts)
        assert all(0 <= c < n for c in cuts), (n_steps, budget_units, cuts)


if __name__ == "__main__":
    test_low_cut_density_never_merges_two_full_steps()
    test_cuts_land_at_end_of_run_not_mid_run()
    test_plan_cuts_boundary_snap_invariants_stress()
    print("All PLAN_CUTS boundary-snap tests passed.")
