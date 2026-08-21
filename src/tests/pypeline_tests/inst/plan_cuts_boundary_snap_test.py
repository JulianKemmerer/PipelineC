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
#
# ...and then the snap itself turned out to be the NEXT bug, in the opposite
# regime: being a fraction of the budget, it scaled with the budget, so once
# the budget fell BELOW one repeated unit it waited forward for the unit's
# own end and built a stage 51% over budget. On the real divider every target
# from 167 to 250 MHz collapsed onto the identical 33-cut plan (measured
# 169.57 MHz local sky130 v4 - the same fmax the 32-cut plan already had, for
# one extra stage). PLAN_CUTS is now two passes with no tolerance at all:
# fewest cuts that fit the budget, then the tightest budget that still needs
# only that many cuts. The tests below therefore assert the INVARIANTS
# (never exceed budget unless physically forced; monotone; minimal; tight)
# rather than any particular snap behavior.
import math
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


def test_discarded_tail_boundary_never_hides_useful_legal_cuts():
    # A final-unit output boundary is intentionally removed when it is not
    # fixed: otherwise it creates an empty trailing comb region.  It must not
    # first be used as a forward snap target, because that skips the useful
    # bit-split sites before it and then deletes the chosen tail cut.
    landscape = SWEEP.SliceLandscape("wide_leaf", 100, 1.0)
    seg = SWEEP.Segment(
        "wide_leaf____minus",
        "BIN_OP_MINUS_uint8_t_uint8_t",
        0.0,
        100.0,
        SWEEP.Segment.SLICEABLE,
    )
    seg.max_legal_units = 8
    seg.ancestor_funcs = {"wide_leaf", seg.func_name}
    landscape.segments.append(seg)
    landscape.finalize({})

    cuts = SWEEP.PLAN_CUTS(landscape, 25.0)
    assert cuts == [13, 28, 42, 56, 70, 85], cuts
    assert SWEEP.PREDICTED_STAGE_NS(cuts, landscape) <= 25.0




def _build_divider_landscape(n_steps=32, minus_bits=34):
    """The REAL reported divider's shape, which the landscape above omits:
    the NOT is parallel (it reads MINUS's output and feeds q_out, not
    remainder), so the serial chain per iteration is just
    [SLICEABLE MINUS][SLICEABLE_1LL MUX] = 7.119ns - and crucially the MINUS
    carries ``max_legal_units``, so finalize() rasterizes bit-internal cut
    sites inside it. Without those sites there is nothing between "one cut
    per iteration" and "two cuts per iteration" to find."""
    step_ns = MINUS_NS + MUX_NS
    total_units = int(round(n_steps * step_ns / UNITS_TO_NS))
    landscape = SWEEP.SliceLandscape("div", total_units, UNITS_TO_NS)
    pos = 0.0
    for i in range(n_steps):
        minus_end = pos + MINUS_NS / UNITS_TO_NS
        minus = SWEEP.Segment(
            f"div__for_i_{i}__minus", "BIN_OP_MINUS_uint34_t_uint34_t",
            pos, minus_end, SWEEP.Segment.SLICEABLE,
        )
        minus.max_legal_units = minus_bits
        minus.ancestor_funcs = {"div", minus.func_name}
        landscape.segments.append(minus)
        mux_end = minus_end + MUX_NS / UNITS_TO_NS
        mux = SWEEP.Segment(
            f"div__for_i_{i}__mux", "MUX_uint32_t", minus_end, mux_end,
            SWEEP.Segment.SLICEABLE_1LL,
        )
        mux.ancestor_funcs = {"div", mux.func_name}
        landscape.segments.append(mux)
        pos = mux_end
    landscape.finalize({})
    return landscape


def _min_cuts_bruteforce(landscape, budget):
    """Independent minimum-cut reference: shortest path over legal positions.
    Deliberately not the planner's own algorithm."""
    n = landscape.total_units
    w = landscape.weight
    prefix = [0.0] * (n + 1)
    for u in range(n):
        prefix[u + 1] = prefix[u] + w[u]

    def span(a, b):  # weight of units a..b inclusive
        return prefix[b + 1] - prefix[a]

    INF = float("inf")
    # best[u] = fewest cuts to have a cut exactly at u, covering 0..u
    best = [INF] * n
    for u in range(n):
        if not landscape.legal[u]:
            continue
        if span(0, u) <= budget + 1e-9:
            best[u] = 1
        for v in range(u):
            if best[v] < INF and span(v + 1, u) <= budget + 1e-9:
                best[u] = min(best[u], best[v] + 1)
    out = INF
    for u in range(n):
        if best[u] < INF and span(u + 1, n - 1) <= budget + 1e-9:
            out = min(out, best[u])
    if span(0, n - 1) <= budget + 1e-9:
        out = min(out, 0)
    return out


def test_stage_never_exceeds_budget_unless_physically_forced():
    # The invariant the old boundary-snap violated by design. A stage may be
    # over budget ONLY when no legal position inside it would have fit -
    # asserted against landscape.legal, not taken on faith.
    landscape = _build_divider_landscape()
    for mhz in range(40, 320, 7):
        budget = (1000.0 / mhz) / UNITS_TO_NS
        cuts = SWEEP.PLAN_CUTS(landscape, budget)
        bounds = [-1] + list(cuts) + [landscape.total_units - 1]
        for i in range(len(bounds) - 1):
            lo, hi = bounds[i] + 1, bounds[i + 1]
            stage = sum(landscape.weight[u] for u in range(lo, hi + 1))
            if stage <= budget + 1e-9:
                continue
            acc = 0.0
            escape = None
            for u in range(lo, hi):
                acc += landscape.weight[u]
                if landscape.legal[u] and acc <= budget + 1e-9:
                    escape = u
            assert escape is None, (
                f"{mhz}MHz: stage [{lo},{hi}] is {stage:.1f} units against a "
                f"{budget:.1f} budget, yet legal unit {escape} would have fit"
            )


def test_no_plan_spends_registers_it_does_not_earn():
    # The reported bug, stated as the invariant that actually matters. Every
    # goal from 167 to 250 MHz used to produce the same 33-cut plan, whose
    # predicted worst stage (7.00ns) was identical to the 32-cut plan's - one
    # register bank per stage bought literally nothing, and the measured fmax
    # confirmed it (169.57 MHz for both, local sky130 v4).
    #
    # Asserted on REALIZED placements, not raster cuts: the raster is where
    # the old planner looked good and the hardware did not. A plan may only
    # use more cuts than another reachable plan if it is genuinely faster.
    landscape = _build_divider_landscape()
    plans = {}
    for mhz in range(60, 300, 4):
        budget = (1000.0 / mhz) / UNITS_TO_NS
        cuts, _p = SWEEP.PLAN_PIPELINE_PLACEMENTS(landscape, budget)
        plans[mhz] = (len(cuts), SWEEP.PREDICTED_STAGE_NS(cuts, landscape))
    ordered = sorted(plans.items())
    for (mhz_a, (n_a, _)), (mhz_b, (n_b, _)) in zip(ordered, ordered[1:]):
        assert n_b >= n_a, (
            f"raising the goal {mhz_a}->{mhz_b} MHz REDUCED cuts {n_a}->{n_b}"
        )
    for mhz_a, (n_a, ns_a) in ordered:
        for mhz_b, (n_b, ns_b) in ordered:
            if n_a > n_b:
                assert ns_a < ns_b - 1e-9, (
                    f"{mhz_a}MHz's plan uses {n_a} cuts but realizes "
                    f"{ns_a:.2f}ns, no better than {mhz_b}MHz's {n_b}-cut "
                    f"plan at {ns_b:.2f}ns - registers bought nothing"
                )


def test_cut_count_is_minimal_for_the_budget():
    # Pass 1's claim, checked against an independent shortest-path minimum.
    landscape = _build_divider_landscape(n_steps=4)
    for mhz in (60, 90, 120, 160, 200, 260):
        budget = (1000.0 / mhz) / UNITS_TO_NS
        cuts = SWEEP.PLAN_CUTS(landscape, budget)
        floor_ns = landscape.floor_ns
        if 1000.0 / mhz < floor_ns:
            continue  # below the atomic floor: minimality is not defined
        ref = _min_cuts_bruteforce(landscape, budget)
        assert len(cuts) <= ref + 1, (
            f"{mhz}MHz: planner used {len(cuts)} cuts, minimum is {ref}"
        )


def test_budget_just_above_one_iteration_cuts_on_the_boundary():
    # Guards the reported 33-stage solution. Pass 1 alone would take the
    # furthest fitting site, ~0.23ns PAST the iteration boundary and 2 bits
    # into a 34-bit subtractor - same cut count, ragged hardware. Pass 2 must
    # pull every cut back onto the iteration boundary.
    landscape = _build_divider_landscape()
    one_step = MINUS_NS + MUX_NS
    budget = (one_step * 1.04) / UNITS_TO_NS  # a 7.4ns goal on a 7.119ns step
    cuts = SWEEP.PLAN_CUTS(landscape, budget)
    # Structural, not a ns tolerance: the axis is rasterized to whole delay
    # units, so "on the boundary" means exactly the MUX-output unit of some
    # iteration - the same unit finalize() derives from ceil(seg.end) - 1.
    boundary_units = {
        min(landscape.total_units, int(math.ceil(seg.end))) - 1
        for seg in landscape.segments
        if seg.func_name == "MUX_uint32_t"
    }
    off = [c for c in cuts if c not in boundary_units]
    assert not off, (
        f"cuts drifted off the iteration boundary into a MINUS interior: "
        f"{off[:6]} (boundaries near: {sorted(boundary_units)[:6]})"
    )
    assert len(cuts) <= 33, cuts



def _build_parallel_branch_landscape():
    """One divider iteration's REAL topology: the NOT is parallel to the MUX,
    not in series before it. Both read BIN_OP_MINUS's output; the NOT feeds
    q_out while the MUX feeds remainder, so their segments OVERLAP on the
    delay axis instead of following one another."""
    landscape = SWEEP.SliceLandscape("div", 72, UNITS_TO_NS)
    minus = SWEEP.Segment(
        "div____minus", "BIN_OP_MINUS_uint34_t_uint34_t",
        0.0, 38.51, SWEEP.Segment.SLICEABLE,
    )
    minus.max_legal_units = 34
    minus.ancestor_funcs = {"div", minus.func_name}
    not_seg = SWEEP.Segment(
        "div____not", "UNARY_OP_NOT_uint1_t",
        38.51, 46.66, SWEEP.Segment.SLICEABLE_1LL,
    )
    not_seg.ancestor_funcs = {"div", not_seg.func_name}
    mux = SWEEP.Segment(
        "div____mux", "MUX_uint32_t",
        38.51, 71.19, SWEEP.Segment.SLICEABLE_1LL,
    )
    mux.ancestor_funcs = {"div", mux.func_name}
    landscape.segments += [minus, not_seg, mux]
    landscape.finalize({})
    return landscape


def test_parallel_branch_output_is_not_a_stage_boundary():
    # The NOT's output boundary lands strictly INSIDE the parallel MUX's
    # atomic span. A register there cuts only the NOT branch while the MUX
    # path crosses the same depth uncut, so it creates no pipeline stage.
    # Left legal, it silently inflates the cut count without deepening the
    # pipeline: the real divider planned 48 cuts and built 32 slices, 16 of
    # them wasted on NOT outputs exactly like this.
    landscape = _build_parallel_branch_landscape()
    not_unit = min(landscape.total_units, int(math.ceil(46.66))) - 1
    mux_unit = min(landscape.total_units, int(math.ceil(71.19))) - 1
    minus_unit = min(landscape.total_units, int(math.ceil(38.51))) - 1
    assert not landscape.legal[not_unit], (
        f"unit {not_unit} (UNARY_OP_NOT output) is inside the parallel "
        f"MUX span [38.51, 71.19) and must not be a legal stage boundary"
    )
    # ...while the boundaries that DO cut every path stay legal: the MUX's
    # own output, and the MINUS output where both branches begin.
    assert landscape.legal[mux_unit], "MUX's own output boundary must stay legal"
    assert landscape.legal[minus_unit], (
        "BIN_OP_MINUS's output boundary must stay legal - both parallel "
        "branches start there, so a register at that depth cuts both"
    )
    assert not any(
        c.func_name == "UNARY_OP_NOT_uint1_t" for c in landscape.candidates
    ), [c.candidate_id for c in landscape.candidates]


def test_bit_splitting_is_dropped_when_it_does_not_pay_once_realized():
    # MATERIALIZE_BIT_PLACEMENT_REQUESTS emits EQUAL-WIDTH bit boundaries
    # chosen from how many requests land in a leaf, so a lone request
    # anywhere in a 34-bit subtractor becomes a split at bit 17 no matter
    # what fraction was asked for. The real divider at a 190 MHz goal asked
    # for 3.9%, 11.8% and 51.3% and got the midpoint for all of them: 48
    # cuts whose REALIZED worst stage was 7.00ns, exactly what the 32-cut
    # boundary-only plan already achieved, for 16 extra register banks.
    # A plan must never be kept when the boundary-only plan realizes at
    # least as good a worst stage with no more cuts.
    landscape = _build_divider_landscape()
    boundary_only = SWEEP._LANDSCAPE_WITHOUT_BIT_SITES(landscape)
    for mhz in (100, 135.5, 145, 167, 190, 214, 260):
        budget = (1000.0 / mhz) / UNITS_TO_NS
        cuts, _placements = SWEEP.PLAN_PIPELINE_PLACEMENTS(landscape, budget)
        alt_cuts, _alt = SWEEP.PLAN_PIPELINE_PLACEMENTS(boundary_only, budget)
        if not alt_cuts:
            continue
        got = (SWEEP.PREDICTED_STAGE_NS(cuts, landscape), len(cuts))
        alt = (SWEEP.PREDICTED_STAGE_NS(alt_cuts, landscape), len(alt_cuts))
        assert got <= alt, (
            f"{mhz}MHz: kept a bit-splitting plan realizing "
            f"{got[0]:.2f}ns with {got[1]} cuts, when operation boundaries "
            f"alone realize {alt[0]:.2f}ns with {alt[1]} cuts"
        )

if __name__ == "__main__":
    test_low_cut_density_never_merges_two_full_steps()
    test_cuts_land_at_end_of_run_not_mid_run()
    test_plan_cuts_boundary_snap_invariants_stress()
    test_discarded_tail_boundary_never_hides_useful_legal_cuts()
    test_stage_never_exceeds_budget_unless_physically_forced()
    test_no_plan_spends_registers_it_does_not_earn()
    test_cut_count_is_minimal_for_the_budget()
    test_budget_just_above_one_iteration_cuts_on_the_boundary()
    test_parallel_branch_output_is_not_a_stage_boundary()
    test_bit_splitting_is_dropped_when_it_does_not_pay_once_realized()
    print("All PLAN_CUTS boundary-snap tests passed.")
