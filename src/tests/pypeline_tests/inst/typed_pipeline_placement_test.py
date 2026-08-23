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
        self.wire_driven_by = {}
        self.wire_drives = {}

    def CAN_HAVE_ADDED_LATENCY(self, _parser_state):
        return True


class FakeParserState:
    def __init__(self, inst_to_logic):
        self.LogicInstLookupTable = dict(inst_to_logic)
        self.FuncLogicLookupTable = {
            logic.func_name: logic for logic in inst_to_logic.values()
        }
        self.func_fixed_latency = {}
        self.func_marked_no_add_io_regs = set()


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


def test_input_boundary_is_a_typed_local_placement():
    root = FakeLogic("main")
    step = FakeLogic(
        "step", ["x"], ["out"], {"x": "uint8_t", "out": "uint8_t"}
    )
    ps = FakeParserState({"main": root, "main__step": step})
    tpl = {inst: SYN.TimingParams(inst, logic) for inst, logic in ps.LogicInstLookupTable.items()}
    boundary = SWEEP.PipelinePlacement(
        SWEEP.PipelinePlacement.INSTANCE_INPUT, "main__step", "step", 0, 0.0
    )
    SWEEP.APPLY_PIPELINE_PLACEMENTS([boundary], ps, tpl)
    assert tpl["main__step"]._has_input_regs
    assert not tpl["main__step"]._has_output_regs
    record = SWEEP.PIPELINE_PLACEMENT_REALIZATION(boundary, ps, tpl)
    assert record["realized"]
    assert record["boundary_register"] == "input"


def _minisweep_chain_fixture(n=10):
    marker = SWEEP.C_TO_LOGIC.SUBMODULE_MARKER
    root = FakeLogic("main")
    step = FakeLogic(
        "step", ["x"], ["out"], {"x": "uint8_t", "out": "uint8_t"}
    )
    inst_to_logic = {"main": root}
    insts = []
    for i in range(n):
        local = f"step_{i}"
        inst = f"main{marker}{local}"
        insts.append(inst)
        inst_to_logic[inst] = step
        root.submodule_instances[local] = "step"
        root.wire_driven_by[f"{local}{marker}x"] = (
            "top_x" if i == 0 else f"step_{i - 1}{marker}out"
        )
    ps = FakeParserState(inst_to_logic)
    ps.FuncToInstances = {"step": insts}
    plan = SWEEP.MainSweepPlan("main", 100.0)
    for inst in insts:
        plan.locked[inst] = SWEEP.MiniSweepLock([0.5])
    return plan, ps, insts


def test_minisweep_serial_topology_shares_one_boundary_per_edge():
    plan, ps, insts = _minisweep_chain_fixture()
    assert SWEEP.SET_MINISWEEP_BOUNDARY_STRATEGY(
        plan, "step", "topology_output", ps
    )
    diag = plan.mini_sweep_boundary_diagnostics["step"]
    assert len(diag["direct_edges"]) == len(insts) - 1
    assert diag["selected_outputs"] == insts[:-1]
    assert diag["selected_inputs"] == []
    assert all(not plan.locked[inst].has_input_regs for inst in insts)
    assert all(plan.locked[inst].has_output_regs for inst in insts[:-1])
    assert not plan.locked[insts[-1]].has_output_regs

    assert SWEEP.SET_MINISWEEP_BOUNDARY_STRATEGY(
        plan, "step", "topology_input", ps
    )
    assert not plan.locked[insts[0]].has_input_regs
    assert all(plan.locked[inst].has_input_regs for inst in insts[1:])
    assert all(not plan.locked[inst].has_output_regs for inst in insts)


def test_minisweep_topology_does_not_cross_an_operation():
    plan, ps, insts = _minisweep_chain_fixture(2)
    root = ps.LogicInstLookupTable["main"]
    marker = SWEEP.C_TO_LOGIC.SUBMODULE_MARKER
    op = FakeLogic("op", ["x"], ["out"], {"x": "uint8_t", "out": "uint8_t"})
    ps.FuncLogicLookupTable["op"] = op
    root.submodule_instances["op"] = "op"
    root.wire_driven_by[f"step_1{marker}x"] = f"op{marker}out"
    assert SWEEP.FIND_DIRECT_LOCKED_BOUNDARY_EDGES(plan, "step", ps) == []


def test_minisweep_boundary_cover_respects_no_io_pragma_and_fingerprint():
    plan, ps, insts = _minisweep_chain_fixture(2)
    ps.func_marked_no_add_io_regs.add("step")
    SWEEP.SET_MINISWEEP_BOUNDARY_STRATEGY(plan, "step", "topology_output", ps)
    diag = plan.mini_sweep_boundary_diagnostics["step"]
    assert not diag["selected_inputs"] and not diag["selected_outputs"]
    assert len(diag["uncovered_edges"]) == 1
    no_io_fingerprint = SWEEP.PIPELINE_PLACEMENT_FINGERPRINT({}, plan.locked)
    ps.func_marked_no_add_io_regs.clear()
    SWEEP.SET_MINISWEEP_BOUNDARY_STRATEGY(plan, "step", "topology_output", ps)
    with_io_fingerprint = SWEEP.PIPELINE_PLACEMENT_FINGERPRINT({}, plan.locked)
    assert no_io_fingerprint != with_io_fingerprint
    assert plan.locked[insts[0]].has_output_regs


def test_minisweep_boundary_cover_shares_fanout_and_fanin_banks():
    # One producer bank covers all fanout edges; one consumer bank covers all
    # fanin edges.  This is why a real bipartite cover is preferable to an
    # instance-order greedy walk.
    outputs, inputs, uncovered = SWEEP._MIN_COST_BIPARTITE_BOUNDARY_COVER(
        [("a", "b"), ("a", "c")], {"a": 8}, {"b": 8, "c": 8}, True
    )
    assert (outputs, inputs, uncovered) == (["a"], [], [])
    outputs, inputs, uncovered = SWEEP._MIN_COST_BIPARTITE_BOUNDARY_COVER(
        [("a", "c"), ("b", "c")], {"a": 8, "b": 8}, {"c": 8}, True
    )
    assert (outputs, inputs, uncovered) == ([], ["c"], [])


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


def test_exact_typed_bit_boundaries_lower_and_hash_distinctly():
    leaf = FakeLogic(
        "BIN_OP_MINUS_uint10_t_uint10_t", ["left", "right"], ["out"],
        {"left": "uint10_t", "right": "uint10_t", "out": "uint10_t"},
    )
    ps = FakeParserState({"main__leaf": leaf})
    tpl = {"main__leaf": SYN.TimingParams("main__leaf", leaf)}
    placements = []
    for ordinal, boundary in enumerate((2, 7), start=1):
        placements.append(SWEEP.PipelinePlacement(
            SWEEP.PipelinePlacement.BIT_INTERNAL,
            "main__leaf", leaf.func_name,
            boundary - 1, float(boundary), local_slice=boundary / 10.0,
            bit_width=10, bit_split_ordinal=ordinal, bit_split_count=2,
            bit_boundary=boundary, bit_boundary_mode="exact",
            bit_boundaries=(2, 7), leaf_axis_start=0.0, leaf_axis_end=10.0,
        ))
    SWEEP.APPLY_PIPELINE_PLACEMENTS(placements, ps, tpl)
    tp = tpl["main__leaf"]
    assert tp._slices == [0.2, 0.7]
    assert tp._exact_bit_boundaries == [2, 7]
    assert RAW_VHDL.GET_BITS_PER_STAGE_DICT(10, tp) == {0: 2, 1: 5, 2: 3}
    assert all(p.bits_per_stage == (2, 5, 3) for p in placements)
    SWEEP.CHECK_PIPELINE_PLACEMENTS_REALIZED(placements, ps, tpl)

    exact_hash = tp.GET_HASH_EXT(tpl, ps)
    equal_tp = SYN.TimingParams("main__leaf", leaf)
    equal_tp.SET_SLICES([0.2, 0.7])
    equal_hash = equal_tp.GET_HASH_EXT({"main__leaf": equal_tp}, ps)
    assert exact_hash != equal_hash


def test_internal_exact_bit_boundary_group_resolves_without_raster_aliasing():
    leaf = FakeLogic(
        "BIN_OP_MINUS_uint10_t_uint10_t", ["left", "right"], ["out"],
        {"left": "uint10_t", "right": "uint10_t", "out": "uint10_t"},
    )
    ps = FakeParserState({"main": FakeLogic("main"), "main__leaf": leaf})
    landscape = SWEEP.SliceLandscape("main", 10, 1.0)
    segment = SWEEP.Segment(
        "main__leaf", leaf.func_name, 0.0, 10.0, SWEEP.Segment.SLICEABLE
    )
    segment.max_legal_units = 10
    landscape.segments.append(segment)
    landscape.finalize({})
    plan = SWEEP.MainSweepPlan("main", 100.0)
    plan.subtrees = ["main"]
    plan.landscapes = {"main": landscape}
    config = {
        "version": 1,
        "mode": "replace",
        "selectors": [],
        "exact_bit_boundaries": [
            {"instance_path": "main__leaf", "boundaries": [2, 7]}
        ],
    }
    SWEEP.RESOLVE_INTERNAL_PIPELINE_PLACEMENTS(config, {"main": plan}, ps)
    selected = plan.fixed_placements["main"]
    assert [p.bit_boundary for p in selected] == [2, 7]
    assert all(p.bit_boundary_mode == "exact" for p in selected)
    assert all(p.bit_boundaries == (2, 7) for p in selected)


def test_chunked_mux_refinement_replaces_outputs_and_covers_terminal_tail():
    insts = [f"main__mux_{index}" for index in range(3)]
    muxes = {
        inst: FakeLogic(
            "MUX_uint8_t",
            ["cond", "iftrue", "iffalse"],
            ["return_output"],
            {
                "cond": "uint1_t",
                "iftrue": "uint8_t",
                "iffalse": "uint8_t",
                "return_output": "uint8_t",
            },
        )
        for inst in insts
    }
    ps = FakeParserState({"main": FakeLogic("main"), **muxes})
    landscape = SWEEP.SliceLandscape("main", 30, 1.0)
    for index, inst in enumerate(insts):
        start = float(index * 10)
        end = start + 10.0
        segment = SWEEP.Segment(
            inst,
            "MUX_uint8_t",
            start,
            end,
            SWEEP.Segment.SLICEABLE_1LL,
        )
        landscape.segments.append(segment)
        landscape.add_candidate(
            SWEEP.PipelinePlacement(
                SWEEP.PipelinePlacement.INSTANCE_OUTPUT,
                inst,
                "MUX_uint8_t",
                int(end) - 1,
                end - 0.5,
                registered_bits=8,
                span_units=10.0,
            )
        )
    landscape.finalize({})
    selected = [
        placement
        for placement in landscape.candidates
        if placement.inst_path in insts[:2]
        and placement.kind == SWEEP.PipelinePlacement.INSTANCE_OUTPUT
    ]
    refinement = SWEEP.BUILD_CHUNKED_MUX_REFINEMENT(
        selected, landscape, ps
    )
    assert refinement is not None
    cuts, placements = refinement
    assert len(cuts) == 3
    assert len(placements) == 3
    assert {placement.inst_path for placement in placements} == set(insts)
    assert all(
        placement.kind == SWEEP.PipelinePlacement.BIT_INTERNAL
        and placement.bit_boundary_mode == "exact"
        and placement.bit_boundaries == (4,)
        and placement.source == "same_depth_mux_refinement"
        for placement in placements
    )
    assert SWEEP.PIPELINE_PLACEMENT_FINGERPRINT({"main": selected}) != (
        SWEEP.PIPELINE_PLACEMENT_FINGERPRINT({"main": placements})
    )

    # MUXes deliberately remain atomic in the ordinary landscape, so the
    # internal exact-boundary experiment hook must derive their span from the
    # concrete output candidate instead of requiring a raster bit request.
    plan = SWEEP.MainSweepPlan("main", 100.0)
    plan.subtrees = ["main"]
    plan.landscapes = {"main": landscape}
    SWEEP.RESOLVE_INTERNAL_PIPELINE_PLACEMENTS(
        {
            "version": 1,
            "mode": "replace",
            "selectors": [],
            "exact_bit_boundaries": [
                {"instance_path": insts[0], "boundaries": [3]}
            ],
        },
        {"main": plan},
        ps,
    )
    forced = plan.fixed_placements["main"]
    assert len(forced) == 1
    assert forced[0].bit_boundary == 3
    assert forced[0].bit_boundaries == (3,)


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
    test_exact_typed_bit_boundaries_lower_and_hash_distinctly()
    test_internal_exact_bit_boundary_group_resolves_without_raster_aliasing()
    test_chunked_mux_refinement_replaces_outputs_and_covers_terminal_tail()
    test_internal_selector_is_deterministic_and_strict()
    test_internal_placement_file_rejects_empty_request()
    print("All typed pipeline-placement tests passed.")
