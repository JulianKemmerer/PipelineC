#!/usr/bin/env python3
"""Pure unit coverage for typed autopipeline placement and lowering."""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../"))

import SWEEP
import SYN
import RAW_VHDL


class FakeLogic:
    def __init__(self, func_name, inputs=(), outputs=(), wire_to_c_type=None):
        self.func_name = func_name
        self.inputs = list(inputs)
        self.outputs = list(outputs)
        self.wire_to_c_type = dict(wire_to_c_type or {})
        self.submodule_instances = {}

    def CAN_HAVE_ADDED_LATENCY(self, _parser_state):
        return True


class FakeParserState:
    def __init__(self, inst_to_logic):
        self.LogicInstLookupTable = dict(inst_to_logic)
        self.FuncLogicLookupTable = {
            logic.func_name: logic for logic in inst_to_logic.values()
        }
        self.func_fixed_latency = {}


def _landscape():
    landscape = SWEEP.SliceLandscape("main", 12, 0.1)
    seg = SWEEP.Segment(
        "main__leaf", "BIN_OP_MINUS_uint8_t_uint8_t", 0.0, 12.0,
        SWEEP.Segment.SLICEABLE,
    )
    seg.max_legal_units = 8
    seg.ancestor_funcs = {"main", seg.func_name}
    landscape.segments.append(seg)
    landscape.add_candidate(
        SWEEP.PipelinePlacement(
            SWEEP.PipelinePlacement.INSTANCE_OUTPUT,
            "main__step", "step", 5, 5.5,
            registered_bits=33, hierarchy_depth=1, span_units=6.0,
            coherent_boundary=True, ancestor_funcs={"main", "step"},
        )
    )
    landscape.finalize({})
    return landscape


def test_landscape_exposes_typed_candidates():
    landscape = _landscape()
    kinds = {p.kind for p in landscape.candidates}
    assert SWEEP.PipelinePlacement.INSTANCE_OUTPUT in kinds
    assert SWEEP.PipelinePlacement.BIT_INTERNAL in kinds
    assert all(landscape.legal[u] for u in landscape.candidates_by_unit)
    bit_sites = [
        p
        for p in landscape.candidates
        if p.kind == SWEEP.PipelinePlacement.BIT_INTERNAL
    ]
    assert bit_sites and all(not p.is_physical for p in bit_sites)
    ids = [p.candidate_id for p in landscape.candidates]
    assert len(ids) == len(set(ids))


def test_coherent_boundary_wins_same_position():
    landscape = _landscape()
    helper = next(p for p in landscape.candidates if p.func_name == "step")
    # Without forcing, a budget that fills at unit 5 must choose the coherent
    # helper boundary over the same-position leaf-internal candidate.
    cuts, placements = SWEEP.PLAN_PIPELINE_PLACEMENTS(landscape, 6.0)
    assert cuts[0] == 5, cuts
    assert placements[0].candidate_id == helper.candidate_id, placements


def test_fixed_position_partitions_budget():
    landscape = _landscape()
    helper = next(p for p in landscape.candidates if p.func_name == "step")
    cuts, placements = SWEEP.PLAN_PIPELINE_PLACEMENTS(
        landscape, 1000.0, [helper.copy_with(fixed=True)]
    )
    assert cuts == [5]
    assert [p.candidate_id for p in placements] == [helper.candidate_id]


def test_slightly_sub_budget_helpers_cut_at_previous_boundary():
    # Divider-gate shape: one complete helper is slightly quicker than the
    # target period.  The budget therefore fills just inside the *next*
    # helper; snapping forward would merge two calls, while the coherent
    # boundary immediately behind is the balanced one-helper-per-stage cut.
    n_steps = 8
    step_units = 10
    landscape = SWEEP.SliceLandscape("main", n_steps * step_units, 1.0)
    for i in range(n_steps):
        lo = i * step_units
        hi = lo + step_units
        seg = SWEEP.Segment(
            f"main__step_{i}__leaf", "BIN_OP_AND_uint1_t_uint1_t",
            float(lo), float(hi), SWEEP.Segment.SLICEABLE_1LL,
        )
        seg.ancestor_funcs = {"main", "step"}
        landscape.segments.append(seg)
        landscape.add_candidate(
            SWEEP.PipelinePlacement(
                SWEEP.PipelinePlacement.INSTANCE_OUTPUT,
                f"main__step_{i}", "step", hi - 1, hi - 0.5,
                hierarchy_depth=1, span_units=step_units,
                coherent_boundary=True, ancestor_funcs={"main", "step"},
            )
        )
    landscape.finalize({})
    cuts, placements = SWEEP.PLAN_PIPELINE_PLACEMENTS(landscape, 12.0)
    assert cuts[:6] == [9, 19, 29, 39, 49, 59], cuts
    assert all(p.func_name == "step" for p in placements), placements
    assert SWEEP.PREDICTED_STAGE_NS(cuts, landscape) <= 12.0


def test_setup_op_and_repeated_helpers_do_not_merge_or_leave_empty_tail():
    # Generic form of the divider's pre-op + N repeated steps.  With the same
    # number of useful boundaries as comb regions, the setup op gets its own
    # boundary, each non-final helper ends at one, and the final helper flows
    # directly to the output (no trailing padding-only register stage).
    n_steps = 5
    setup_units = 3
    step_units = 10
    total = setup_units + n_steps * step_units
    marker = SWEEP.C_TO_LOGIC.SUBMODULE_MARKER
    algorithm_inst = f"main{marker}algorithm"
    landscape = SWEEP.SliceLandscape("main", total, 1.0)
    # Put the setup and helpers one level below an outer coherent wrapper.
    # A global "shallowest output" rule sees only that wrapper and misses the
    # setup MUX; parent-relative sibling discovery must still retain it.
    setup = SWEEP.Segment(
        f"{algorithm_inst}{marker}setup", "MUX_uint16_t",
        0.0, float(setup_units),
        SWEEP.Segment.SLICEABLE_1LL,
    )
    setup.ancestor_funcs = {"main", "algorithm"}
    landscape.segments.append(setup)
    for i in range(n_steps):
        lo = setup_units + i * step_units
        hi = lo + step_units
        seg = SWEEP.Segment(
            f"{algorithm_inst}{marker}step_{i}{marker}leaf",
            "BIN_OP_AND_uint1_t_uint1_t",
            float(lo), float(hi), SWEEP.Segment.SLICEABLE_1LL,
        )
        seg.ancestor_funcs = {"main", "algorithm", "step"}
        landscape.segments.append(seg)
        landscape.add_candidate(
            SWEEP.PipelinePlacement(
                SWEEP.PipelinePlacement.INSTANCE_OUTPUT,
                f"{algorithm_inst}{marker}step_{i}", "step",
                hi - 1, hi - 0.5,
                hierarchy_depth=2, span_units=step_units,
                coherent_boundary=True,
                ancestor_funcs={"main", "algorithm", "step"},
            )
        )
    landscape.add_candidate(
        SWEEP.PipelinePlacement(
            SWEEP.PipelinePlacement.INSTANCE_OUTPUT,
            algorithm_inst, "algorithm", total - 1, total - 0.5,
            hierarchy_depth=1, span_units=total,
            coherent_boundary=True, ancestor_funcs={"main", "algorithm"},
        )
    )
    landscape.finalize({})
    cuts, placements = SWEEP.PLAN_PIPELINE_PLACEMENTS(landscape, 10.0)
    assert cuts == [2, 12, 22, 32, 42], cuts
    assert cuts[-1] < total - 1
    assert placements[0].func_name == "MUX_uint16_t"
    assert all(p.func_name == "step" for p in placements[1:])
    assert SWEEP.PREDICTED_STAGE_NS(cuts, landscape) <= 10.0


def test_planner_component_weights_change_geometry_not_total_budget():
    landscape = SWEEP.SliceLandscape("main", 10, 1.0)
    left = SWEEP.Segment(
        "main__left", "BIN_OP_MINUS_uint8_t_uint8_t", 0.0, 5.0,
        SWEEP.Segment.SLICEABLE,
    )
    right = SWEEP.Segment(
        "main__right", "BIN_OP_MINUS_uint8_t_uint8_t", 5.0, 10.0,
        SWEEP.Segment.SLICEABLE,
    )
    # Both realistic ratios are below one; this specifically guards against
    # initializing the per-unit max at 1.0 and silently clamping them away.
    left.planner_scale = 0.25
    right.planner_scale = 0.75
    landscape.segments += [left, right]
    landscape.finalize({})
    assert sum(landscape.weight) == 10.0
    assert sum(landscape.weight[:5]) < sum(landscape.weight[5:])
    assert landscape.weight[5] == 3.0 * landscape.weight[0]


def test_typed_lowering_is_local_not_recursive():
    root = FakeLogic("main", outputs=["out"], wire_to_c_type={"out": "uint8_t"})
    step = FakeLogic("step", outputs=["out"], wire_to_c_type={"out": "uint8_t"})
    leaf = FakeLogic(
        "BIN_OP_MINUS_uint8_t_uint8_t", ["left", "right"], ["out"],
        {"left": "uint8_t", "right": "uint8_t", "out": "uint8_t"},
    )
    ps = FakeParserState({"main": root, "main__step": step, "main__leaf": leaf})
    tpl = {inst: SYN.TimingParams(inst, logic) for inst, logic in ps.LogicInstLookupTable.items()}
    boundary = SWEEP.PipelinePlacement(
        SWEEP.PipelinePlacement.INSTANCE_OUTPUT, "main__step", "step", 5, 5.5
    )
    internal = SWEEP.PipelinePlacement(
        SWEEP.PipelinePlacement.BIT_INTERNAL, "main__leaf", leaf.func_name,
        5, 6.0, local_slice=0.5,
        bit_width=8, bit_split_ordinal=1, bit_split_count=1,
        bit_boundary=4, leaf_axis_start=0.0, leaf_axis_end=12.0,
    )
    SWEEP.APPLY_PIPELINE_PLACEMENTS([boundary, internal], ps, tpl)
    assert tpl["main__step"]._has_output_regs
    assert tpl["main__leaf"]._slices == [0.5]
    assert tpl["main"].IS_EMPTY()
    assert not tpl["main__leaf"]._has_output_regs
    SWEEP.CHECK_PIPELINE_PLACEMENTS_REALIZED([boundary, internal], ps, tpl)


def test_minisweep_zero_cut_pass_never_locks_io_only_latency():
    """An isolated helper that already meets timing needs no IO-only lock.

    The repeated-hotspot escalation deliberately happens early.  This keeps
    it harmless for a repeated helper such as Divider's one-step function
    when its isolated implementation already meets the target: a successful
    zero-cut probe must leave all instances untouched rather than adding two
    clocks of input/output registers to each one.
    """
    root = FakeLogic("main")
    step = FakeLogic("step")
    step.delay_is_estimated = False
    ps = FakeParserState(
        {"main": root, "main__step_0": step, "main__step_1": step}
    )
    ps.FuncToInstances = {"step": ["main__step_0", "main__step_1"]}
    plan = SWEEP.MainSweepPlan("main", 100.0)
    plan.subtrees = ["main"]

    class MetState:
        met_timing = True
        initial_guess_latency = 0

    old_has_hier = SWEEP.SYN.FUNC_HAS_HIER_ALLOWING_ADDED_LATENCY_TO_RAW_VHDL
    old_coarse = SWEEP.SYN.DO_COARSE_THROUGHPUT_SWEEP
    try:
        SWEEP.SYN.FUNC_HAS_HIER_ALLOWING_ADDED_LATENCY_TO_RAW_VHDL = (
            lambda _func, _ps: True
        )
        SWEEP.SYN.DO_COARSE_THROUGHPUT_SWEEP = (
            lambda *_args, **_kwargs: (MetState(), [], None)
        )
        assert not SWEEP.RUN_HOTSPOT_MINISWEEP("step", plan, ps)
        assert plan.locked == {}
    finally:
        SWEEP.SYN.FUNC_HAS_HIER_ALLOWING_ADDED_LATENCY_TO_RAW_VHDL = old_has_hier
        SWEEP.SYN.DO_COARSE_THROUGHPUT_SWEEP = old_coarse


def test_bit_requests_materialize_to_raw_equal_width_boundaries():
    # Deliberately request two very uneven raster positions. Raw VHDL ignores
    # those fractions and emits three balanced chunks; the planner must return
    # physical placements at exactly the same cumulative bit boundaries.
    landscape = SWEEP.SliceLandscape("main", 100, 1.0)
    requests = [
        SWEEP.BitPlacementRequest(
            "main__leaf", "BIN_OP_MINUS_uint10_t_uint10_t",
            8, 8.5, 0.085, 10, 0.0, 100.0,
            registered_bits=10,
        ),
        SWEEP.BitPlacementRequest(
            "main__leaf", "BIN_OP_MINUS_uint10_t_uint10_t",
            86, 86.5, 0.865, 10, 0.0, 100.0,
            registered_bits=10,
        ),
    ]
    placements = SWEEP.MATERIALIZE_BIT_PLACEMENT_REQUESTS(requests, landscape)
    assert all(isinstance(p, SWEEP.PipelinePlacement) for p in placements)
    assert [p.bit_boundary for p in placements] == [3, 7]
    assert [p.bit_split_ordinal for p in placements] == [1, 2]
    assert [p.local_slice for p in placements] == [0.3, 0.7]
    assert [p.axis_unit for p in placements] == [29, 69]
    assert [list(p.bits_per_stage) for p in placements] == [
        [3, 4, 3], [3, 4, 3]
    ]
    assert RAW_VHDL.GET_EQUAL_WIDTH_BIT_BOUNDARIES(10, 2) == [3, 7]

    planned_landscape = SWEEP.SliceLandscape("main", 100, 1.0)
    seg = SWEEP.Segment(
        "main__leaf", "BIN_OP_MINUS_uint10_t_uint10_t",
        0.0, 100.0, SWEEP.Segment.SLICEABLE,
    )
    seg.max_legal_units = 10
    planned_landscape.segments.append(seg)
    planned_landscape.finalize({})
    planned_cuts, planned = SWEEP.PLAN_PIPELINE_PLACEMENTS(
        planned_landscape, 25.0
    )
    assert planned_cuts == [19, 39, 59, 79]
    assert [p.bit_boundary for p in planned] == [2, 4, 6, 8]
    assert all(p.is_physical for p in planned)

    leaf = FakeLogic(
        "BIN_OP_MINUS_uint10_t_uint10_t", ["left", "right"], ["out"],
        {"left": "uint10_t", "right": "uint10_t", "out": "uint10_t"},
    )
    ps = FakeParserState({"main__leaf": leaf})
    tpl = {"main__leaf": SYN.TimingParams("main__leaf", leaf)}
    SWEEP.APPLY_PIPELINE_PLACEMENTS(placements, ps, tpl)
    assert tpl["main__leaf"]._slices == [0.3, 0.7]
    emitted = RAW_VHDL.GET_BITS_PER_STAGE_DICT(10, tpl["main__leaf"])
    assert emitted == {0: 3, 1: 4, 2: 3}
    records = [
        SWEEP.PIPELINE_PLACEMENT_REALIZATION(p, ps, tpl) for p in placements
    ]
    assert all(record["realized"] for record in records)
    assert all(record["bits_per_stage"] == [3, 4, 3] for record in records)
    assert [record["bit_boundary"] for record in records] == [3, 7]
    assert records[0]["requested_local_slice"] == 0.085
    assert records[0]["local_slice"] == 0.3

    try:
        SWEEP.APPLY_PIPELINE_PLACEMENTS(requests, ps, tpl)
        assert False, "provisional raster requests must never lower directly"
    except ValueError as e:
        assert "provisional bit planning site" in str(e)


def test_internal_selector_is_deterministic_and_strict():
    landscape = _landscape()
    ps = FakeParserState({"main": FakeLogic("main"), "main__step": FakeLogic("step")})
    plan = SWEEP.MainSweepPlan("main", 100.0)
    plan.subtrees = ["main"]
    plan.landscapes = {"main": landscape}
    plans = {"main": plan}
    config = {
        "version": 1, "mode": "replace",
        "selectors": [{"kind": "instance_output", "func_name": "step", "all": True}],
    }
    SWEEP.RESOLVE_INTERNAL_PIPELINE_PLACEMENTS(config, plans, ps)
    selected = plan.fixed_placements["main"]
    assert len(selected) == 1 and selected[0].fixed
    assert plan.placement_mode == "replace"
    bad = dict(config)
    bad["selectors"] = [{"func_name": "does_not_exist", "all": True}]
    try:
        SWEEP.RESOLVE_INTERNAL_PIPELINE_PLACEMENTS(bad, plans, ps)
        assert False, "unmatched forced selector must fail"
    except ValueError as e:
        assert "matched no legal candidate" in str(e)


def test_internal_placement_file_rejects_empty_request():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as f:
        json.dump({"version": 1, "mode": "replace"}, f)
        f.flush()
        try:
            SWEEP.LOAD_INTERNAL_PLACEMENT_CONFIG(
                {SWEEP.INTERNAL_PLACEMENT_FILE_ENV: f.name}
            )
            assert False, "an empty forced-placement request must fail"
        except ValueError as e:
            assert "at least one selector" in str(e)


if __name__ == "__main__":
    test_landscape_exposes_typed_candidates()
    test_coherent_boundary_wins_same_position()
    test_fixed_position_partitions_budget()
    test_slightly_sub_budget_helpers_cut_at_previous_boundary()
    test_setup_op_and_repeated_helpers_do_not_merge_or_leave_empty_tail()
    test_planner_component_weights_change_geometry_not_total_budget()
    test_typed_lowering_is_local_not_recursive()
    test_minisweep_zero_cut_pass_never_locks_io_only_latency()
    test_bit_requests_materialize_to_raw_equal_width_boundaries()
    test_internal_selector_is_deterministic_and_strict()
    test_internal_placement_file_rejects_empty_request()
    print("All typed pipeline-placement tests passed.")
