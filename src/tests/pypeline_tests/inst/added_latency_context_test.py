#!/usr/bin/env python3
"""Compiler-added latency stays within an absorbing caller context; no synthesis."""
import copy
import functools
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import AUTO_PIPELINE as AP
import C_TO_LOGIC
import PY_TO_LOGIC
import SWEEP
import SYN

M = C_TO_LOGIC.SUBMODULE_MARKER


@functools.lru_cache(None)
def _state():
    with tempfile.TemporaryDirectory() as out, patch.object(SYN, "SYN_OUTPUT_DIRECTORY", out):
        ps = PY_TO_LOGIC.PARSE_FILE(str(Path(__file__).with_name("added_latency_context_design.py")))
        for logic in ps.FuncLogicLookupTable.values():
            if not logic.submodule_instances:
                logic.delay = 0 if SYN.LOGIC_IS_ZERO_DELAY(logic, ps) else 10
        with patch.object(SYN, "HIER_SYN_MODE", "prim"):
            ordered = SYN.RECURSIVE_GET_FUNCS_FOR_PATH_DELAYS(list(ps.main_mhz), ps)
        SYN.ESTIMATE_HIER_PATH_DELAYS(
            [f for f in ordered if ps.FuncLogicLookupTable[f].submodule_instances], ps, quiet=True
        )
    return ps


def _empty(ps):
    return {inst: AP.TimingParams(inst, logic) for inst, logic in ps.LogicInstLookupTable.items()}


def _func(ps, name):
    return next(f for f in ps.FuncToInstances if f == name or f.endswith("_" + name))


def _insts(ps, name):
    return sorted(ps.FuncToInstances[_func(ps, name)])


def _under(inst, root):
    return inst == root or inst.startswith(root + M)


def _plans(ps):
    plans = [SWEEP.MainSweepPlan(main, 80.0) for main in sorted(ps.main_mhz)]
    for plan in plans:
        plan.subtrees = SWEEP.COLLECT_CUT_SUBTREES(plan.main_inst, ps)
    return plans


def _holders(ps):
    return {i: l for i, l in ps.LogicInstLookupTable.items() if l.mcp_tuples}


def _coarse(inst, mhz, state, ps, **kwargs):
    state.met_timing = True
    state.initial_guess_latency = 1
    return state, [0.5], None


def _locked_plans(ps):
    plans = _plans(ps)
    with patch.object(SWEEP, "DO_COARSE_THROUGHPUT_SWEEP", side_effect=_coarse) as probe, patch.object(SYN, "MEASURE_DELAYS"):
        for plan in plans:
            assert SWEEP.RUN_HOTSPOT_MINISWEEP(_func(ps, "helper"), plan, ps)
            assert SWEEP.HOTSPOT_IS_LOCKED(_func(ps, "helper"), plan, ps)
        assert probe.call_count == 2
        assert all(_under(call.args[0], plan.main_inst) for call, plan in zip(probe.call_args_list, plans))
    return plans


def _raises_unchanged(ps, tpl, inst, operation, mcp=False):
    before = {i: tp.DEEPCOPY() for i, tp in tpl.items()}
    try:
        operation()
    except ValueError as err:
        blocker = AP.ADDED_LATENCY_BLOCKER(inst, ps)
        assert blocker in str(err), str(err)
        assert ps.LogicInstLookupTable[blocker].func_name in str(err), str(err)
        if mcp:
            assert "multi-cycle" in str(err) and "launch -> capture" in str(err), str(err)
    else:
        raise AssertionError("illegal added latency accepted: " + inst)
    assert {i: vars(tp) for i, tp in tpl.items()} == {i: vars(tp) for i, tp in before.items()}


def test_per_main_targets_and_all_boundary_strategies():
    ps = _state()
    holders = _holders(ps)
    assert len(holders) == 2
    assert sum(bool(l.auto_multi_cycle_tuples) for l in holders.values()) == 1
    plans = _locked_plans(ps)
    for plan in plans:
        targets, excluded = SWEEP.MINISWEEP_LOCK_TARGETS(_func(ps, "helper"), plan, ps)
        assert len(targets) == 1 and len(excluded) == 3, (targets, excluded)
        body = next(i for i in _insts(ps, "ap_body") if _under(i, plan.main_inst))
        assert _under(targets[0], body)
        holder = next(i for i in holders if _under(i, plan.main_inst))
        for inst, blocker in excluded.items():
            assert blocker == (holder if _under(inst, holder) else plan.main_inst)
        assert set(plan.mini_sweep_boundary_diagnostics[_func(ps, "helper")]["excluded_instances"]) == set(excluded)
    assert not (set(plans[0].locked) & set(plans[1].locked))
    for strategy in ("topology_output", "topology_input", "all_output", "all_input", "both"):
        tpl = _empty(ps)
        for plan in plans:
            assert SWEEP.SET_MINISWEEP_BOUNDARY_STRATEGY(plan, _func(ps, "helper"), strategy, ps)
            SWEEP.APPLY_LOCKS(plan, ps, tpl)
        AP.CHECK_ADDED_LATENCY_CONTEXTS(ps, tpl)
        for inst, params in tpl.items():
            if AP.ADDED_LATENCY_BLOCKER(inst, ps) is not None:
                assert params.IS_EMPTY(), inst
        for plan in plans:
            root = next(iter(plan.locked))
            assert any(tp._slices for i, tp in tpl.items() if _under(i, root) and not ps.LogicInstLookupTable[i].submodule_instances)
        for holder, logic in holders.items():
            pm = AP.GET_PIPELINE_MAP(holder, logic, ps, tpl)
            assert pm.num_stages == 1, (holder, pm.num_stages)
            for local in logic.submodule_instances:
                child = holder + M + local
                assert tpl[child].GET_TOTAL_LATENCY(ps, tpl) == 0, child
            # Every child's output is produced at stage 0 (including constant networks).
            # GET_PIPELINE_MAP retains an empty terminal StageInfo sentinel.
            assert all(
                not stage.submodule_output_ports
                and all(not level.submodule_insts for level in stage.submodule_level_infos)
                for stage in pm.stage_infos[1:]
            )
            stages = [pm.stage_infos[0], pm.const_network_stage_info, pm.read_only_global_network_stage_info]
            scheduled = {
                local for stage in stages if stage is not None
                for level in stage.submodule_level_infos for local in level.submodule_insts
            }
            assert scheduled == set(logic.submodule_instances), (holder, scheduled)


def test_guards_reject_before_mutating():
    ps = _state()
    holders = _holders(ps)
    for holder in holders:
        interior = next(i for i in _insts(ps, "helper") if _under(i, holder))
        tpl = _empty(ps)
        plan = next(p for p in _plans(ps) if _under(holder, p.main_inst))
        plan.locked[interior] = SWEEP.MiniSweepLock([0.5])
        _raises_unchanged(ps, tpl, interior, lambda: SWEEP.APPLY_LOCKS(plan, ps, tpl), mcp=True)
        leaf = next(i for i, l in ps.LogicInstLookupTable.items() if _under(i, interior) and not l.submodule_instances and l.CAN_HAVE_ADDED_LATENCY(ps))
        _raises_unchanged(ps, tpl, leaf, lambda: AP.SLICE_DOWN_HIERARCHY_WRITE_VHDL_PACKAGES(leaf, ps.LogicInstLookupTable[leaf], 0.5, ps, tpl, False, write_files=False), mcp=True)
    for inst in _insts(ps, "helper"):
        if AP.ADDED_LATENCY_BLOCKER(inst, ps) is None:
            continue
        tpl = _empty(ps)
        placement = SWEEP.PipelinePlacement(SWEEP.PipelinePlacement.INSTANCE_OUTPUT, inst, _func(ps, "helper"), 0, 0.5)
        _raises_unchanged(ps, tpl, inst, lambda: SWEEP.APPLY_PIPELINE_PLACEMENTS([placement], ps, tpl), mcp=any(_under(inst, h) for h in holders))


def test_prewrite_safety_net_and_bookkeeping():
    ps = _state()
    for holder in _holders(ps):
        leaf = next(i for i, l in ps.LogicInstLookupTable.items() if _under(i, holder) and not l.submodule_instances and l.CAN_HAVE_ADDED_LATENCY(ps))
        for kind in ("slices", "out", "in", "exact"):
            tpl = _empty(ps)
            if kind == "slices":
                tpl[leaf].SET_SLICES([0.5])
            elif kind == "exact":
                tpl[leaf]._exact_bit_boundaries = [4]
            elif kind == "out":
                tpl[holder].SET_HAS_OUT_REGS(True)
            else:
                tpl[holder].SET_HAS_IN_REGS(True)
            inst = holder if kind in ("out", "in") else leaf
            _raises_unchanged(ps, tpl, inst, lambda: AP.CHECK_ADDED_LATENCY_CONTEXTS(ps, tpl), mcp=True)
            with tempfile.TemporaryDirectory() as out, patch.object(SYN, "SYN_OUTPUT_DIRECTORY", out):
                _raises_unchanged(ps, tpl, inst, lambda: AP.WRITE_ALL_NON_ZERO_CLK_VHDL_FILES(tpl, ps), mcp=True)
                assert not list(Path(out).iterdir())
        tpl = _empty(ps)
        tpl[holder].SET_SLICES([0.5])
        AP.CHECK_ADDED_LATENCY_CONTEXTS(ps, tpl)  # non-leaf bookkeeping


def test_seeding_exact_and_renamed_paths():
    ps = _state()
    prev_tpl = _empty(ps)
    for plan in _locked_plans(ps):
        SWEEP.SET_MINISWEEP_BOUNDARY_STRATEGY(plan, _func(ps, "helper"), "both", ps)
        SWEEP.APPLY_LOCKS(plan, ps, prev_tpl)
    for rename in (False, True):
        new = copy.copy(ps)
        names = {i: i.replace(M, M + "renamed_") if rename else i for i in ps.LogicInstLookupTable}
        new.LogicInstLookupTable = {}
        for i, logic in ps.LogicInstLookupTable.items():
            logic = copy.copy(logic)
            prefix = "renamed_" if rename else ""
            logic.submodule_instances = {prefix + k: v for k, v in logic.submodule_instances.items()}
            logic.sub_inst_to_auto_pipeline_latency = {prefix + k: v for k, v in logic.sub_inst_to_auto_pipeline_latency.items()}
            logic.sub_inst_to_auto_pipeline_key = {prefix + k: v for k, v in logic.sub_inst_to_auto_pipeline_key.items()}
            new.LogicInstLookupTable[names[i]] = logic
        source = {i: tp.DEEPCOPY() for i, tp in prev_tpl.items()}
        # Exact tier must reject a stale, previously illegal interior too.
        if not rename:
            for inst in _insts(ps, "helper"):
                source[inst].SET_HAS_OUT_REGS(True)
        tpl, unseeded = AP.SEED_TIMING_PARAMS_FROM_PREVIOUS(ps, source, new, _empty(new))
        assert not unseeded
        for old_inst, inst in names.items():
            if AP.ADDED_LATENCY_BLOCKER(inst, new) is not None:
                assert tpl[inst].IS_EMPTY(), inst
            elif not prev_tpl[old_inst].IS_EMPTY():
                assert tpl[inst]._slices == prev_tpl[old_inst]._slices, inst
                assert tpl[inst]._has_output_regs == prev_tpl[old_inst]._has_output_regs
        AP.CHECK_ADDED_LATENCY_CONTEXTS(new, tpl)


def test_gap_planning_and_coarse_slicing():
    ps = _state()
    tpl = _empty(ps)
    for plan in _plans(ps):
        bridge = next(i for i in _insts(ps, "bridge") if _under(i, plan.main_inst))
        tagged = next(i for i in _insts(ps, "tagged_gap") if _under(i, bridge))
        helper = next(i for i in _insts(ps, "helper") if _under(i, bridge))
        assert tagged in plan.subtrees and bridge not in plan.subtrees, plan.subtrees
        landscape = SWEEP.BUILD_SLICE_LANDSCAPE(bridge, ps, tpl, {})
        assert landscape is not None
        assert all(_under(p.inst_path, tagged) for p in landscape.candidates)
        own = [seg for seg in landscape.segments if not _under(seg.inst_path, tagged)]
        assert own and all(seg.kind == SWEEP.Segment.ATOMIC and seg.reason == "inside_state_regs_container" and seg.hard for seg in own)
        # Try all delay offsets from MAIN; bookkeeping may accumulate but no
        # physical register is allowed in the untagged bridge/helper logic.
        pm = AP.GET_ZERO_ADDED_CLKS_PIPELINE_MAP(plan.main_inst, ps.LogicInstLookupTable[plan.main_inst], ps)
        for offset in range(int(pm.zero_clk_max_delay)):
            trial = _empty(ps)
            AP.SLICE_DOWN_HIERARCHY_WRITE_VHDL_PACKAGES(plan.main_inst, ps.LogicInstLookupTable[plan.main_inst], (offset + 0.5) / pm.zero_clk_max_delay, ps, trial, False, write_files=False)
            assert all(tp.IS_EMPTY() for i, tp in trial.items() if _under(i, helper)), helper
            AP.CHECK_ADDED_LATENCY_CONTEXTS(ps, trial)


def test_only_stateful_callers_and_self_timed_do_not_decouple():
    ps = copy.copy(_state())
    ps.FuncToInstances = dict(ps.FuncToInstances)
    name = _func(ps, "helper")
    ps.FuncToInstances[name] = [i for i in ps.FuncToInstances[name] if AP.ADDED_LATENCY_BLOCKER(i, ps) is not None]
    for plan in _plans(ps):
        assert SWEEP.WHY_HOTSPOT_NOT_PIPELINABLE(name, ps, plan) == "inside_state_regs_container"
        with patch.object(SWEEP, "DO_COARSE_THROUGHPUT_SWEEP") as probe:
            assert not SWEEP.RUN_HOTSPOT_MINISWEEP(name, plan, ps)
            probe.assert_not_called()
        logic = ps.LogicInstLookupTable[plan.main_inst]
        # Self-timed children (user fixed latency) never authorize compiler latency.
        with patch.object(logic, "submodule_latencies_are_self_timed", set(logic.submodule_instances)):
            assert not SWEEP.MINISWEEP_LOCK_TARGETS(name, plan, ps)[0]
    # A stateful instance that blocks itself keeps its own (soft) reason.
    for holder in _holders(ps):
        reason, message = AP.DESCRIBE_ADDED_LATENCY_BLOCKER(holder, holder, ps)
        assert reason == "state_regs" and reason in SWEEP.SOFT_FLOOR_REASONS, reason
        assert "cannot hold added pipeline latency" in message, message
    # A directly tagged call inside an MCP is still explicitly authorized.
    for holder, logic in _holders(ps).items():
        local = next(k for k, f in logic.submodule_instances.items() if f in {_func(ps, "prologue"), _func(ps, "epilogue")})
        tags = dict(logic.sub_inst_to_auto_pipeline_latency)
        tags[local] = C_TO_LOGIC.AutoPipelineLatency()
        with patch.object(logic, "sub_inst_to_auto_pipeline_latency", tags):
            interior = next(i for i in _insts(ps, "helper") if _under(i, holder))
            assert AP.ADDED_LATENCY_BLOCKER(interior, ps) is None


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
