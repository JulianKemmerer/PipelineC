#!/usr/bin/env python3
"""Unit coverage for the constrained-AUTOPIPELINE region planner in SWEEP.py
(AUTOPIPELINE(func, latency= / start_latency= / max_latency=)):

  - COUNT_TARGETED_PLACEMENTS plans exactly K cuts on a landscape, spread for
    the tightest stages, and refuses (strict) or clamps more cuts than there
    are legal register positions;
  - _TRIM_PLACEMENT_PLAN_TO_COUNT reduces a larger plan to K;
  - AutopipelineRegion cap bookkeeping and REGION_FOR_HOTSPOT attribution.

Synthetic SliceLandscape fixtures (the typed_pipeline_placement_test.py
pattern); lowering, realized-latency verification and locking are exercised
end to end by autopipeline_constraints_test.py and the fixed-latency
native_vs_vhdl compares.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../"))

import C_TO_LOGIC
import SWEEP

M = C_TO_LOGIC.SUBMODULE_MARKER
AL = C_TO_LOGIC.AutopipelineLatency
N_OPS = 6
UNITS_PER_OP = 10


def _chain_landscape(n_ops=N_OPS, units_per_op=UNITS_PER_OP):
    """A chain of equal-delay operations whose only legal register positions
    are the operations' outputs (n_ops - 1 useful cuts)."""
    landscape = SWEEP.SliceLandscape("region", n_ops * units_per_op, 0.1)
    for i in range(n_ops):
        inst = f"region{M}op{i}"
        seg = SWEEP.Segment(
            inst,
            "BIN_OP_MUX_uint8_t",
            float(i * units_per_op),
            float((i + 1) * units_per_op),
            SWEEP.Segment.SLICEABLE_1LL,
        )
        seg.ancestor_funcs = {"region", seg.func_name}
        landscape.segments.append(seg)
    landscape.finalize({})
    return landscape


def test_exact_counts():
    landscape = _chain_landscape()
    for count in range(0, N_OPS):
        cuts, placements, budget = SWEEP.COUNT_TARGETED_PLACEMENTS(landscape, count)
        assert len(cuts) == count, (count, cuts)
        assert len(placements) >= count, (count, placements)
        assert budget > 0.0
    # Spread for the tightest stages: 1 cut splits 6 ops 3/3, 2 cuts 2/2/2
    cuts, _, _ = SWEEP.COUNT_TARGETED_PLACEMENTS(landscape, 1)
    assert cuts == [3 * UNITS_PER_OP - 1], cuts
    cuts, _, _ = SWEEP.COUNT_TARGETED_PLACEMENTS(landscape, 2)
    assert cuts == [2 * UNITS_PER_OP - 1, 4 * UNITS_PER_OP - 1], cuts


def test_more_cuts_than_positions():
    landscape = _chain_landscape()
    n_legal = sum(1 for legal in landscape.legal if legal)
    try:
        SWEEP.COUNT_TARGETED_PLACEMENTS(landscape, n_legal + 1)
    except SWEEP.AutopipelineLatencyInfeasible as err:
        assert "legal register position" in str(err), str(err)
    else:
        raise AssertionError("strict count beyond legal positions accepted")
    cuts, _, _ = SWEEP.COUNT_TARGETED_PLACEMENTS(
        landscape, n_legal + 1, strict=False
    )
    assert len(cuts) <= n_legal, cuts


def test_trim_plan_to_count():
    landscape = _chain_landscape()
    over = SWEEP.COUNT_TARGETED_PLACEMENTS(landscape, 4)
    trimmed = SWEEP._TRIM_PLACEMENT_PLAN_TO_COUNT(landscape, over, 2)
    assert trimmed is not None
    cuts, placements, _ = trimmed
    assert len(cuts) == 2, cuts
    assert all(p.axis_unit in cuts for p in placements)


class _FakePlan:
    def __init__(self, main_inst, regions):
        self.main_inst = main_inst
        self.regions = regions


class _FakeParserState:
    def __init__(self, func_to_instances):
        self.FuncToInstances = func_to_instances


def test_region_caps_and_hotspot_attribution():
    fixed = SWEEP.AutopipelineRegion(f"main{M}r0", AL(latency=2), "key_fixed", "core")
    capped = SWEEP.AutopipelineRegion(f"main{M}r1", AL(max_latency=3), None, "core2")
    started = SWEEP.AutopipelineRegion(f"main{M}r2", AL(start_latency=1), "key_s", "core3")
    assert capped.group == ("inst", capped.inst) and fixed.group == "key_fixed"
    assert started.start_pending and not fixed.start_pending
    fixed.realized = 2
    capped.realized = 2
    started.realized = 9
    assert fixed.at_cap() and not capped.at_cap() and not started.at_cap()
    capped.realized = 3
    assert capped.at_cap()

    plan = _FakePlan("main", [fixed, capped, started])
    ps = _FakeParserState(
        {
            "leaf": {f"main{M}r0{M}leaf"},
            "shared": {f"main{M}r0{M}x", f"main{M}r1{M}x"},
            "outside": {f"main{M}glue"},
            "elsewhere": {f"other_main{M}r0{M}leaf"},
        }
    )
    assert SWEEP.REGION_FOR_HOTSPOT("leaf", plan, ps) is fixed
    assert SWEEP.REGION_FOR_HOTSPOT("shared", plan, ps) is None  # two groups
    assert SWEEP.REGION_FOR_HOTSPOT("outside", plan, ps) is None
    assert SWEEP.REGION_FOR_HOTSPOT("elsewhere", plan, ps) is None
    assert SWEEP.REGION_FOR_HOTSPOT("leaf", _FakePlan("main", []), ps) is None


if __name__ == "__main__":
    test_exact_counts()
    test_more_cuts_than_positions()
    test_trim_plan_to_count()
    test_region_caps_and_hotspot_attribution()
    print("All AUTOPIPELINE region planning unit tests passed.")
