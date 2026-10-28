#!/usr/bin/env python3
"""Cold synthesis scheduling over an elaborated design; no vendor tools run."""

import contextlib
import io
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import AUTO_MULTI_CYCLE as MCP
import AUTO_PIPELINE as AP
import LOGIC
import PY_TO_LOGIC
import SYN
import SWEEP
import pypeline

DESIGN = Path(__file__).with_name("synthesis_scope_design.py")


@contextlib.contextmanager
def characterized(mode="leaf", cached_delay=None, prepare=None, delay_model=None):
    calls = []

    def synth(inst, logic, *args, **kwargs):
        SYN.REUSE_ONLY_MISS()
        calls.append((inst, logic.func_name))
        return SimpleNamespace(path_reports={})

    def measured(logic, *args):
        logic.delay = 10
        logic.delay_is_estimated = False

    with tempfile.TemporaryDirectory() as out, contextlib.ExitStack() as stack:
        backend = SimpleNamespace(SYN_AND_REPORT_TIMING=synth, __name__="FAKE")
        for obj, name, value in [
            (SYN, "SYN_OUTPUT_DIRECTORY", out),
            (SYN, "SYN_TOOL", backend),
            (SYN, "HIER_SYN_MODE", mode),
            (SYN, "PART_SET_TOOL", lambda *a, **k: None),
            (SYN, "TOOL_DOES_PNR", lambda: False),
            (SYN, "GET_CACHED_PATH_DELAY", cached_delay or (lambda *a: None)),
            (SYN, "SET_STORED_DELAY", lambda *a: False),
            (SYN, "WRITE_BLACK_BOX_FILES", lambda *a: None),
            (SYN, "SET_MEASURED_DELAY_FROM_REPORT", measured),
            (SYN, "GET_NUM_PROCESSES", lambda: 1),
            (SYN, "USE_PRIMITIVE_DELAY_MODEL", delay_model is not None),
            (SYN, "PrimitiveDelayModel", lambda _cache_dir: delay_model),
            (MCP, "ISOLATED_MCP_EVIDENCE", {}),
        ]:
            stack.enter_context(patch.object(obj, name, value))
        stack.enter_context(
            patch.dict("os.environ", {"PIPELINEC_INTERNAL_SKIP_PIPELINE_MAP_PNG": "1"})
        )
        pypeline.SET_AUTO_PIPELINE_BUILD_MODE("sweep")
        pypeline.SET_AUTO_PIPELINE_LATENCY_CACHE({})
        pypeline.SET_AUTO_MULTI_CYCLE_LATENCY_CACHE({})
        with contextlib.redirect_stdout(io.StringIO()):
            ps = PY_TO_LOGIC.PARSE_FILE(str(DESIGN))
            if prepare is not None:
                prepare(ps)
            SYN.ADD_PATH_DELAY_TO_LOOKUP(ps)
        yield ps, calls


def test_bank_helpers_are_estimated_from_primitive_dependencies():
    with characterized() as (ps, calls):
        banks = [
            l
            for l in ps.FuncLogicLookupTable.values()
            if l.func_name.startswith("VAR_REF")
        ]
        assert banks and all(l.submodule_instances for l in banks)
        called = {f for _, f in calls}
        assert not called.intersection(l.func_name for l in banks), called
        assert all(l.delay is not None and l.delay_is_estimated for l in banks)
        assert any(f.startswith("MUX_") for f in called), called


def test_shared_pipeline_helper_is_measured_without_authorizing_blocked_calls():
    with characterized() as (ps, calls):
        shared = next(f for f in ps.FuncToInstances if f.endswith("shared_math"))
        geometry_calls = [(i, f) for i, f in calls if f == shared]
        assert len(geometry_calls) == 1, geometry_calls
        blockers = [AP.ADDED_LATENCY_BLOCKER(i, ps) for i in ps.FuncToInstances[shared]]
        assert None in blockers and any(b is not None for b in blockers)


def test_stateful_surroundings_have_no_standalone_hierarchy_measurements():
    with characterized() as (ps, calls):
        ordinary = [
            f
            for _, f in calls
            if not ps.FuncLogicLookupTable[f].auto_multi_cycle_tuples
        ]
        assert all(
            SYN.PATH_DELAY_IS_PRIMITIVE(ps.FuncLogicLookupTable[f])
            or not SYN.FUNC_SUBTREE_HAS_STATE(f, ps)
            for f in ordinary
        )
        neighbor = next(
            l
            for f, l in ps.FuncLogicLookupTable.items()
            if f.endswith("stateful_neighbor")
        )
        assert neighbor.delay_is_estimated and neighbor.delay is not None
        assert not SYN.STORED_DELAY_IS_USABLE(neighbor, ps)


def test_opaque_text_starts_at_zero_without_standalone_measurement():
    with characterized() as (ps, calls):
        opaque = [
            ps.FuncLogicLookupTable[f]
            for f in ps.path_delay_funcs
            if ps.FuncLogicLookupTable[f].vhdl_module_text is not None
        ]
        assert opaque
        assert all(l.delay == 0 and l.delay_is_estimated for l in opaque)
        assert not any(ps.FuncLogicLookupTable[f].vhdl_module_text for _, f in calls)
        assert all(not SYN.PATH_DELAY_IS_PRIMITIVE(l) for l in opaque)


def test_opaque_text_does_not_consult_cached_scalar_delays_in_any_mode():
    def cached(logic, ps):
        assert logic.vhdl_module_text is None, logic.func_name
        return None

    for mode in ("leaf", "prim", "full"):
        with characterized(mode, cached) as (ps, calls):
            opaque = [
                l
                for l in ps.FuncLogicLookupTable.values()
                if l.vhdl_module_text is not None and l.delay is not None
            ]
            assert opaque and all(l.delay == 0 for l in opaque)
            assert all(not SYN.STORED_DELAY_IS_USABLE(l, ps) for l in opaque)


def test_unrelated_controller_has_no_geometry_jobs():
    with characterized() as (ps, calls):
        assert not any(
            i == "unrelated_main" or i.startswith("unrelated_main____")
            for i, _ in calls
        )
        assert not any("PLUS_uint64" in f for _, f in calls)


def _mark_scheduled_fsm(ps):
    # After scheduling, the AUTO_FSM call site points at a generated stateful FSM.
    main = ps.FuncLogicLookupTable["fsm_main"]
    local = next(l for l, f in main.submodule_instances.items() if f == "fsm_stand_in")
    main.sub_inst_to_auto_fsm_key = {local: "scope_fsm"}


def test_scheduled_fsm_is_one_measured_atomic_span():
    # Measuring the units inside a scheduled FSM replaced the operation delays
    # carried from the bootstrap pass, so rescheduling saw different numbers
    # (auto_fsm_timing_iter_test oscillated; warm copies rescheduled).
    with characterized(prepare=_mark_scheduled_fsm) as (ps, calls):
        fsm = ps.FuncLogicLookupTable["fsm_stand_in"]
        assert [f for _, f in calls if f == "fsm_stand_in"] == ["fsm_stand_in"]
        assert not fsm.delay_is_estimated
        inside = set(fsm.submodule_instances.values())
        assert inside and not inside.intersection(ps.path_delay_funcs), (
            inside.intersection(ps.path_delay_funcs)
        )
        assert not any(f == "fsm_main" for _, f in calls)


def test_scheduled_fsm_takes_its_delay_from_the_installed_schedule():
    # A whole-module run of each generated FSM took 8 minutes on WireGuard and
    # reported an input-to-output figure. With a schedule installed, its worst
    # state (or a longer measured pinned-unit stage) is the delay instead.
    import pypeline

    pypeline.SET_AUTO_FSM_SCHEDULE_CACHE({"scope_fsm": dict(
        worst_state_du=95,
        implementations={"unit": dict(placement_digest="d3", worst_stage_du=90)},
        unit_measurements={"d3": dict(worst_stage_du=104)},
    )})
    try:
        with characterized(prepare=_mark_scheduled_fsm) as (ps, calls):
            fsm = ps.FuncLogicLookupTable["fsm_stand_in"]
            assert not any(f == "fsm_stand_in" for _, f in calls), calls
            assert fsm.delay == 104 and fsm.delay_is_estimated, fsm.delay
            inside = set(fsm.submodule_instances.values())
            assert not inside.intersection(ps.path_delay_funcs)
    finally:
        pypeline.SET_AUTO_FSM_SCHEDULE_CACHE({})


def test_primitive_widths_are_estimated_instead_of_synthesized():
    # A width the tool has not measured is estimated from measured widths
    # (SYN.PrimitiveDelayModel), marked as an estimate with its error bound.
    # Primitives the model does not cover are still synthesized.
    class Model:
        def estimate(self, func_name):
            return (2.5, 0.3) if func_name.startswith("BIN_OP_PLUS_") else None

    with characterized(delay_model=Model()) as (ps, calls):
        plus = [
            l
            for f, l in ps.FuncLogicLookupTable.items()
            if f.startswith("BIN_OP_PLUS_") and f in ps.path_delay_funcs
        ]
        assert plus
        assert not any(f.startswith("BIN_OP_PLUS_") for _, f in calls), calls
        assert all(
            l.delay == 25 and l.delay_is_estimated and l.delay_model_error == 3
            for l in plus
        ), [(l.func_name, l.delay, l.delay_model_error) for l in plus]
        assert any(f.startswith("MUX_") for _, f in calls), calls


def test_unmarked_stateful_function_without_consumer_has_no_jobs():
    with characterized() as (ps, calls):
        assert "fsm_stand_in" not in ps.path_delay_funcs
        assert not any(f == "fsm_stand_in" for _, f in calls)


def test_opaque_fallback_requires_failing_path_evidence_in_the_plan():
    with characterized() as (ps, calls):
        opaque = next(
            l
            for f, l in ps.FuncLogicLookupTable.items()
            if f in ps.path_delay_funcs and l.vhdl_module_text is not None
        )
        plan = SimpleNamespace(subtrees=["pipeline_main"], regions=[])
        path = SimpleNamespace(
            start_reg_name="elsewhere/reg", end_reg_name=None, netlist_resources=set()
        )
        assert SWEEP.OPAQUE_PATH_DELAY_REFINEMENTS(path, plan, ps) == set()
        path.netlist_resources = {opaque.func_name + "/fifo_cell"}
        selected = SWEEP.OPAQUE_PATH_DELAY_REFINEMENTS(path, plan, ps)
        assert selected == {opaque.func_name}
        before = len(calls)
        assert SYN.MEASURE_DELAYS(selected, ps) == set()
        assert len(calls) == before
        assert SYN.MEASURE_DELAYS(selected, ps, refine_opaque=True) == selected
        assert {f for _, f in calls[before:]} == selected
        assert opaque.delay == 10 and not opaque.delay_is_estimated
        assert SYN.MEASURE_DELAYS(selected, ps, refine_opaque=True) == set()


def test_mcp_endpoint_evidence_is_separate_from_geometry_and_reused_by_shape():
    with characterized() as (ps, calls):
        holders = [
            (i, f)
            for i, f in calls
            if ps.FuncLogicLookupTable[f].auto_multi_cycle_tuples
        ]
        assert len(holders) == 1, holders
        holder = ps.FuncLogicLookupTable[holders[0][1]]
        # This holder also surrounds a pipeline landscape. Its scalar is an
        # estimate from primitives, never the endpoint report's critical path.
        assert holder.delay_is_estimated
        groups = MCP.COLLECT_AUTO_MULTI_CYCLE_GROUPS(ps)
        for group in groups.values():
            MCP.ISOLATED_MCP_EVIDENCE[(group.key, MCP.MCP_SHAPE(group, ps))] = 30.0
        before = list(calls)
        with SYN.ThreadPool(processes=1) as pool:
            MCP.MEASURE_REQUIRED_ENDPOINTS(
                ps, AP.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(ps), pool
            )
        assert calls == before


def test_opaque_fallback_refreshes_zero_only_ancestor_geometry():
    with characterized() as (ps, calls):
        wrapper = ps.FuncLogicLookupTable["opaque_stage"]
        assert wrapper.delay == 0 and wrapper.delay_is_estimated
        opaque = next(
            ps.FuncLogicLookupTable[f]
            for f in ps.path_delay_funcs
            if ps.FuncLogicLookupTable[f].vhdl_module_text is not None
        )
        SYN.MEASURE_DELAYS([opaque.func_name], ps, refine_opaque=True)
        assert wrapper.delay == 10 and wrapper.delay_is_estimated


def test_fallback_ignores_estimated_surroundings_and_returns_no_change():
    with characterized() as (ps, calls):
        estimated = [
            f
            for f, l in ps.FuncLogicLookupTable.items()
            if l.delay_is_estimated and not SYN.PATH_DELAY_IS_MEASURABLE(l, ps)
        ]
        assert estimated
        before = list(calls)
        assert SYN.MEASURE_DELAYS(estimated, ps) == set()
        assert calls == before


def test_fallback_measures_only_eligible_combinational_estimates():
    with characterized() as (ps, calls):
        helper = next(f for f in ps.FuncToInstances if f.endswith("product_low"))
        assert ps.FuncLogicLookupTable[helper].delay_is_estimated
        estimated = [
            f for f, l in ps.FuncLogicLookupTable.items() if l.delay_is_estimated
        ]
        before = len(calls)
        changed = SYN.MEASURE_DELAYS(estimated, ps)
        assert helper in changed
        assert {f for _, f in calls[before:]} == changed
        assert all(not SYN.FUNC_SUBTREE_HAS_STATE(f, ps) for f in changed)
        assert not ps.FuncLogicLookupTable[helper].delay_is_estimated
        assert SYN.MEASURE_DELAYS(estimated, ps) == set()


def test_fully_combinational_main_retains_frontier_measurement():
    with characterized() as (ps, calls):
        assert sum(f == "pure_main" for _, f in calls) == 1
        assert "pure_main" in ps.path_delay_frontier_funcs


def test_goal_less_combinational_main_has_no_geometry_jobs():
    with characterized() as (ps, calls):
        assert ps.main_mhz["goal_less_main"] is None
        assert "goal_less_main" not in ps.path_delay_funcs
        assert not any(f == "goal_less_main" for _, f in calls)
        assert not any(f.startswith("BIN_OP_PLUS_uint64") for _, f in calls)


def test_goal_less_fixed_latency_region_remains_a_geometry_consumer():
    with characterized() as (ps, calls):
        assert ps.main_mhz["fixed_only_main"] is None
        assert "fixed_only_math" in ps.path_delay_frontier_funcs
        assert any(f == "fixed_only_math" for _, f in calls)
        assert not any(f == "fixed_only_main" for _, f in calls)


def test_delay_scope_is_declared_before_characterization():
    ps = LOGIC.ParserState()
    assert ps.path_delay_funcs is None
    assert ps.path_delay_measure_funcs is None
    assert ps.path_delay_frontier_funcs is None


def test_delay_measurement_requires_explicit_scope_initialization():
    ps = LOGIC.ParserState()
    logic = LOGIC.Logic()
    logic.func_name = "uninitialized"
    try:
        SYN.PATH_DELAY_IS_MEASURABLE(logic, ps)
    except RuntimeError as error:
        assert "ADD_PATH_DELAY_TO_LOOKUP" in str(error)
    else:
        raise AssertionError("measurement silently initialized its own scope")


def test_rooted_characterization_preserves_the_full_parse_scope():
    with characterized() as (ps, calls):
        before = (list(ps.path_delay_funcs), set(ps.path_delay_measure_funcs),
                  set(ps.path_delay_frontier_funcs))
        SYN.ADD_PATH_DELAY_TO_LOOKUP(ps, root_func_names=["shared_math"])
        after = (ps.path_delay_funcs, ps.path_delay_measure_funcs,
                 ps.path_delay_frontier_funcs)
        assert before == after
        assert SYN.PATH_DELAY_IS_MEASURABLE(ps.FuncLogicLookupTable["pure_main"], ps)


def test_parser_state_copy_preserves_independent_delay_scope_collections():
    ps = LOGIC.ParserState()
    ps.path_delay_funcs = ["first", "second"]
    ps.path_delay_measure_funcs = {"first"}
    ps.path_delay_frontier_funcs = {"second"}
    cloned = ps.DEEPCOPY()
    for name in ["path_delay_funcs", "path_delay_measure_funcs", "path_delay_frontier_funcs"]:
        assert getattr(cloned, name) == getattr(ps, name)
        assert getattr(cloned, name) is not getattr(ps, name)


def test_unseeded_goal_having_tag_has_its_own_placement_region():
    with characterized() as (ps, calls):
        regions = [
            r for r in AP.COLLECT_AUTO_PIPELINE_REGIONS(ps) if r.key == "scope_pipeline"
        ]
        assert len(regions) == 1
        assert regions[0].constraint.is_unconstrained()
        assert regions[0].constraint.start() is None


def test_goal_less_unconstrained_tag_has_no_geometry_jobs():
    with characterized() as (ps, calls):
        assert not any(
            r.key == "goal_less_pipeline" for r in AP.COLLECT_AUTO_PIPELINE_REGIONS(ps)
        )
        assert "goal_less_math" not in ps.path_delay_funcs
        assert not any(f == "goal_less_math" for _, f in calls)


def test_tag_placements_do_not_depend_on_surrounding_stateful_delays():
    with characterized() as (ps, calls):

        def placed():
            region = next(
                r
                for r in AP.COLLECT_AUTO_PIPELINE_REGIONS(ps)
                if r.key == "scope_pipeline"
            )
            tpl = AP.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(ps)
            tpl = AP.ENFORCE_AUTO_PIPELINE_REGIONS([region], ps, tpl, period_ns=0.4)
            assert region.realized > 0
            return AP.CAPTURE_CONCRETE_PIPELINE(region.inst, tpl, ps)

        original = placed()
        for name in ["stateful_neighbor", "bank_stage", "pipeline_main"]:
            ps.FuncLogicLookupTable[name].delay *= 100
        AP._GET_ZERO_ADDED_CLKS_PIPELINE_MAP_cache.clear()
        assert placed() == original


def test_estimated_blocked_spans_cannot_establish_a_hard_floor():
    with characterized() as (ps, calls):
        params = AP.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(ps)
        landscape = SWEEP.BUILD_SLICE_LANDSCAPE("pipeline_main", ps, params, {})
        estimated = [
            s
            for s in landscape.segments
            if ps.FuncLogicLookupTable[s.func_name].delay_is_estimated
        ]
        assert estimated
        assert all(not s.hard for s in estimated)


def test_primitive_only_mode_keeps_mcp_evidence_but_skips_comb_frontier():
    with characterized("prim") as (ps, calls):
        assert not any(f.endswith("shared_math") for _, f in calls)
        assert any(ps.FuncLogicLookupTable[f].auto_multi_cycle_tuples for _, f in calls)


def test_explicit_full_hierarchy_mode_retains_unrelated_diagnostics():
    with characterized("full") as (ps, calls):
        assert any(f == "unrelated_main" for _, f in calls)


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
