#!/usr/bin/env python3
"""Sweep recovery, fresh locks, opaque refinement and flattened STA attribution.

No vendor tools run. The actual sweep loop handles feedback, fallback, floor
stops and snapshots; only placement/lowering and backend timing are scripted.
"""

import math
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import AUTO_MULTI_CYCLE as MCP
import AUTO_PIPELINE as AP
import SYN
import SWEEP
import VHDL
from scripted_sweep_backend import ScriptedBackend, path
from sweep_evidence_test import _run_trim_sweep, _scripted_sweep_patches
from typed_pipeline_placement_test import FakeLogic, FakeParserState


def test_flattened_device_model_paths_still_check_every_main():
    ps = FakeParserState({name: FakeLogic(name) for name in ("heavy", "light")})
    ps.main_mhz = {"heavy": 30, "light": 30}
    ps.clk_cross_var_info = {}
    params = SimpleNamespace(TimingParamsLookupTable={})
    report = path("unused", 33.9745)
    report.start_reg_name = "$auto$ff.cc:266:slice$336"
    report.end_reg_name = "$auto$ff.cc:266:slice$341"
    report.netlist_resources = {"$abc$2194$auto$blifparse.cc:396:parse_blif$4643"}
    with patch.object(VHDL, "GET_ENTITY_NAME", lambda inst, *a: inst):
        with patch.object(SYN, "SYN_TOOL", SYN.DEVICE_MODELS):
            assert SWEEP.GET_MAIN_INSTS_FOR_PATH_REPORT(report, ps, params) == {
                "heavy", "light"
            }
        # A vendor path outside the MAINs can belong to a built-in FIFO.
        with patch.object(SYN, "SYN_TOOL", SYN.VIVADO):
            assert SWEEP.GET_MAIN_INSTS_FOR_PATH_REPORT(report, ps, params) == set()


def test_failed_zero_cut_probe_recovers_after_mcp_count_repair():
    group = MCP.AutoMultiCycleGroup("g", SWEEP.LOGIC.AutoMultiCycleConstraint("g"))

    def reports(cuts, params, paths):
        if cuts == 0 and params.auto_multi_cycle_ncycles["g"] == 1:
            paths.append(path("a", 12.0, pair="mcp"))

    def seed(ps, params):
        params.auto_multi_cycle_ncycles["g"] = 1

    patches = [
        (MCP, "COLLECT_AUTO_MULTI_CYCLE_GROUPS", lambda ps: {"g": group}),
        (MCP, "SEED_COUNTS", seed),
        (MCP, "PROPOSE_CONFIRM_DOWN", lambda *a: {}),
        (
            MCP,
            "AUTO_MULTI_CYCLE_GROUP_FOR_PATH_REPORT",
            lambda p, *a: group if "/mcp/" in p.start_reg_name else None,
        ),
    ]
    observed, retained = _run_trim_sweep(
        {1: [9.95, 2], 0: [11.95]},
        effort=1,
        initial_cuts=1,
        report_hook=reports,
        extra_patches=patches,
    )
    assert observed == [1, 0, 1], observed
    assert retained == 1


def test_failed_trim_tests_a_new_helper_lock_before_restoring_the_met_snapshot():
    pipe = "a" + SWEEP.LOGIC.SUBMODULE_MARKER + "pipe"

    def minisweep(func, plan, ps):
        assert func == "pipe_root"
        plan.locked[pipe] = SWEEP.MiniSweepLock([0.5])
        plan.last_failing_total_cuts = None
        return True

    def apply_locks(plan, ps, tpl):
        for inst, lock in plan.locked.items():
            tpl[inst].SET_SLICES(lock.slices)
            tpl[inst].params_are_fixed = True
        return tpl

    observed, retained = _run_trim_sweep(
        {4: [9.0], 3: [12.0], 1: [8.0]},
        effort=1,
        extra_patches=[
            (SWEEP, "RESOLVE_PIPELINABLE_HOTSPOT", lambda *a: ("pipe_root", None, "")),
            (SWEEP, "TRY_HOTSPOT_MINISWEEP", minisweep),
            (SWEEP, "APPLY_LOCKS", apply_locks),
        ],
    )
    assert observed == [4, 3, 1], observed
    assert retained == 1


def test_opaque_path_is_refined_after_combinational_fallback_before_floor_stop():
    marker = SWEEP.LOGIC.SUBMODULE_MARKER
    main, helper, opaque = (FakeLogic(n) for n in ["a", "helper", "opaque"])
    main.submodule_instances = {"h": "helper", "o": "opaque"}
    ps = FakeParserState(
        {"a": main, "a" + marker + "h": helper, "a" + marker + "o": opaque}
    )
    ps.main_mhz = {"a": 100}
    ps.FuncToInstances = {l.func_name: {i} for i, l in ps.LogicInstLookupTable.items()}
    ps.path_delay_funcs = list(ps.FuncLogicLookupTable)
    for logic in ps.FuncLogicLookupTable.values():
        logic.delay, logic.delay_is_estimated = 150, logic is not main
        logic.vhdl_module_text = None
    opaque.delay, opaque.vhdl_module_text = 0, "opaque implementation"

    def fresh(ps):
        return {i: AP.TimingParams(i, l) for i, l in ps.LogicInstLookupTable.items()}

    def landscape(root, *args):
        view = SWEEP.SliceLandscape(root, 200, 0.1)
        seg = SWEEP.Segment(
            root + marker + "op", "helper", 0, 200, SWEEP.Segment.SLICEABLE
        )
        seg.ancestor_funcs = {"a", "helper"}
        view.segments.append(seg)
        view.finalize({})
        view.floor_ns, view.floor_blame = 15.0, seg
        return view

    def placements(view, budget, fixed_placements=()):
        n = math.ceil(3 * view.budget_units_for_period(10.0) / budget)
        cuts = list(range(1, n + 1))
        return cuts, [
            SimpleNamespace(axis_unit=c, to_dict=lambda c=c: {"axis_unit": c})
            for c in cuts
        ]

    def apply(placed, ps, tpl, **kwargs):
        tpl["a" + marker + "h"].SET_SLICES(
            [(i + 1) / (len(placed) + 1.0) for i in range(len(placed))]
        )
        return tpl

    measured = []

    def measure(funcs, ps, refine_opaque=False):
        measured.append(set(funcs))
        assert "opaque" not in funcs or refine_opaque
        for f in funcs:
            ps.FuncLogicLookupTable[f].delay_is_estimated = False
        return set(funcs)

    def rule(ps, params):
        if not opaque.delay_is_estimated:
            return [path("a", 5.0, pair="opaque")]
        return [
            path("a", 15.0, pair="helper" if helper.delay_is_estimated else "opaque")
        ]

    backend = ScriptedBackend(rule)
    params = SimpleNamespace(
        TimingParamsLookupTable=fresh(ps), auto_multi_cycle_ncycles={}
    )
    with tempfile.TemporaryDirectory() as out, ExitStack() as stack:
        extra = [
            (SYN, "SYN_OUTPUT_DIRECTORY", out),
            (SYN, "HIER_SYN_MODE", "leaf"),
            (SYN, "MEASURE_DELAYS", measure),
            (
                SYN,
                "PATH_DELAY_IS_MEASURABLE",
                lambda l, ps, refine_opaque=False: l is helper
                or (l is opaque and refine_opaque),
            ),
            (SWEEP, "MAX_SWEEP_ITERS", 2),
            (SWEEP, "BUILD_SLICE_LANDSCAPE", landscape),
            (SWEEP, "PLAN_PIPELINE_PLACEMENTS", placements),
            (SWEEP, "CHUNK_SELECTED_MUX_OUTPUT_BANKS", lambda placed, *a: placed),
            (SWEEP, "APPLY_PIPELINE_PLACEMENTS", apply),
            (SWEEP, "CHECK_PIPELINE_PLACEMENTS_REALIZED", lambda *a: None),
            (
                SWEEP,
                "DROP_NON_DEEPENING_PLACEMENTS",
                lambda r, cuts, placed, *a: (cuts, placed),
            ),
            (
                SWEEP,
                "PIPELINE_PLACEMENT_FINGERPRINT",
                lambda placed, locked: repr(
                    sorted((k, len(v)) for k, v in placed.items())
                ),
            ),
            (
                AP.TimingParams,
                "GET_TOTAL_LATENCY",
                lambda self, ps, tpl: sum(
                    len(t._slices)
                    for inst, t in tpl.items()
                    if inst == self.inst_name
                    or inst.startswith(self.inst_name + marker)
                ),
            ),
            (
                SWEEP,
                "SUMMARIZE_SUBTREE_PIPELINE",
                lambda m, st, t, p: (False, [], len(t["a" + marker + "h"]._slices)),
            ),
            (
                SWEEP,
                "GET_SUBTREE_PIPELINE_STAGES",
                lambda plan, t, p: len(t["a" + marker + "h"]._slices),
            ),
        ]
        for obj, key, value in _scripted_sweep_patches(backend, fresh, extra):
            stack.enter_context(patch.object(obj, key, value))
        result = SWEEP.DO_PLANNED_THROUGHPUT_SWEEP(ps, params)
    assert measured == [{"helper"}, {"opaque"}], measured
    assert not result.sweep_timing_failures, result.sweep_timing_failures


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
