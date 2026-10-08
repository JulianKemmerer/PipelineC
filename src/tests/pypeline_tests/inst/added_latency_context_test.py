#!/usr/bin/env python3
"""Compiler-added latency stays within an absorbing caller context; no synthesis."""
import copy
import functools
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import AUTO_PIPELINE as AP
import AUTO_MULTI_CYCLE as MCP
import VHDL
import VIVADO
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
    # Same contract as DO_COARSE_THROUGHPUT_SWEEP: the winning table is
    # returned too (the mini-sweep captures its concrete interior).
    state.met_timing = True
    state.initial_guess_latency = 1
    table = AP.ADD_SLICES_DOWN_HIERARCHY_TIMING_PARAMS_AND_WRITE_VHDL_PACKAGES(
        inst, ps.LogicInstLookupTable[inst], [0.5], ps,
        AP.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(ps), write_files=False,
    )
    return state, [0.5], table


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
    # "wrappers" renames each MAIN's direct children, like a latency-sized
    # factory wrapper whose entity name changes; tagged interiors keep their
    # relative paths. "interior" renames every level, which breaks the
    # contract that an AUTO_PIPELINE'd function does not depend on .latency.
    for rename in (None, "wrappers", "interior"):
        new = copy.copy(ps)
        new.LogicInstLookupTable = {}
        names = {}
        for i, logic in ps.LogicInstLookupTable.items():
            logic = copy.copy(logic)
            if rename == "interior" or (rename == "wrappers" and M not in i):
                logic.submodule_instances = {"renamed_" + k: v for k, v in logic.submodule_instances.items()}
                logic.sub_inst_to_auto_pipeline_latency = {"renamed_" + k: v for k, v in logic.sub_inst_to_auto_pipeline_latency.items()}
                logic.sub_inst_to_auto_pipeline_key = {"renamed_" + k: v for k, v in logic.sub_inst_to_auto_pipeline_key.items()}
            names[i] = {None: i, "wrappers": i.replace(M, M + "renamed_", 1), "interior": i.replace(M, M + "renamed_")}[rename]
            new.LogicInstLookupTable[names[i]] = logic
        source = {i: tp.DEEPCOPY() for i, tp in prev_tpl.items()}
        # Exact tier must reject a stale, previously illegal interior too.
        if rename is None:
            for inst in _insts(ps, "helper"):
                source[inst].SET_HAS_OUT_REGS(True)
        if rename == "interior":
            try:
                AP.SEED_TIMING_PARAMS_FROM_PREVIOUS(ps, source, new, _empty(new))
            except AP.SeedReplayError as exc:
                assert "must not depend on .latency" in str(exc), exc
            else:
                raise AssertionError("a changed AUTO_PIPELINE interior was replayed")
            continue
        tpl, unseeded = AP.SEED_TIMING_PARAMS_FROM_PREVIOUS(ps, source, new, _empty(new))
        assert not unseeded
        for old_inst, inst in names.items():
            if AP.ADDED_LATENCY_BLOCKER(inst, new) is not None:
                assert tpl[inst].IS_EMPTY(), inst
            elif not prev_tpl[old_inst].IS_EMPTY():
                assert tpl[inst]._slices == prev_tpl[old_inst]._slices, inst
                assert tpl[inst]._has_output_regs == prev_tpl[old_inst]._has_output_regs
        AP.CHECK_ADDED_LATENCY_CONTEXTS(new, tpl)


def test_holder_rebuilt_for_a_new_count_reuses_its_datapath_evidence():
    """A cycle-count change rebuilds an AUTO_MULTI_CYCLE holder (its handshake
    compares against .latency + 1) without changing the launch-to-capture
    cone. WireGuard re-synthesized such holders for ~17 min per pass. With
    isolated evidence for the same MCP_SHAPE, characterization derives the
    per-cycle delay instead; without it, the holder is synthesized. An
    earlier run of exactly the rebuilt holder (SYN.STORED_MEASUREMENT) beats
    the derivation."""
    import pypeline

    synthesized = []
    stored = set()

    def fake_syn(inst, logic, ps, tpl, *a, **k):
        if logic.func_name in stored:
            # An earlier result: read, not run
            return SimpleNamespace(path_reports={"clk": SimpleNamespace(path_delay_ns=5.0)})
        SYN.REUSE_ONLY_MISS()  # the backend contract: a lookup never runs
        synthesized.append(logic.func_name)
        return logic.func_name

    def fake_measured(logic, report, ps):
        logic.delay = 50
        logic.delay_is_estimated = False

    def characterize(count):
        synthesized.clear()
        # A --syn_cache store is where a fresh output directory finds an
        # earlier run (without one, a lookup needs a log already in the
        # function's own directory); fake_syn stands in for its contents
        store = "<store>" if stored else None
        with tempfile.TemporaryDirectory() as out, patch.object(SYN, "SYN_OUTPUT_DIRECTORY", out), \
                patch.object(SYN, "SYNTHESIS_STORE_DIR", store):
            pypeline.SET_AUTO_MULTI_CYCLE_LATENCY_CACHE({} if count is None else {key: count})
            try:
                ps = PY_TO_LOGIC.PARSE_FILE(str(Path(__file__).with_name("added_latency_context_design.py")))
            finally:
                pypeline.SET_AUTO_MULTI_CYCLE_LATENCY_CACHE({})
            with patch.object(SYN, "SYN_TOOL", SimpleNamespace(SYN_AND_REPORT_TIMING=fake_syn, __name__="FAKE")), \
                    patch.object(SYN, "PART_SET_TOOL", lambda *a, **k: None), \
                    patch.object(SYN, "WRITE_BLACK_BOX_FILES", lambda *a, **k: None), \
                    patch.object(SYN, "GET_CACHED_PATH_DELAY", lambda *a: None), \
                    patch.object(SYN, "GET_NUM_PROCESSES", lambda: 1), \
                    patch.object(SYN, "SET_MEASURED_DELAY_FROM_REPORT", fake_measured), \
                    patch.object(SYN.DEVICE_MODELS, "part_supported", lambda part: False):
                SYN.ADD_PATH_DELAY_TO_LOOKUP(ps)
        holder = next(l for l in ps.FuncLogicLookupTable.values() if l.auto_multi_cycle_tuples)
        group = MCP.COLLECT_AUTO_MULTI_CYCLE_GROUPS(ps)[key]
        return ps, holder, MCP.MCP_SHAPE(group, ps)

    ps = _state()
    key = next(iter(MCP.COLLECT_AUTO_MULTI_CYCLE_GROUPS(ps)))
    with patch.object(MCP, "ISOLATED_MCP_EVIDENCE", {}):
        _ps1, holder1, shape1 = characterize(None)
        assert holder1.func_name in synthesized, synthesized  # no evidence yet
        MCP.ISOLATED_MCP_EVIDENCE[(key, shape1)] = 30.0  # as REMEMBER_ISOLATED_REPORTS records
        _ps3, holder3, shape3 = characterize(3)
        assert holder3.func_name != holder1.func_name  # rebuilt for the count
        assert shape3 == shape1  # same datapath cone
        assert holder3.func_name not in synthesized, synthesized
        assert holder3.delay == int(10.0 * SYN.DELAY_UNIT_MULT), holder3.delay
        # An earlier run of this exact holder: its measurement, not the derivation
        stored.add(holder3.func_name)
        _ps, holder, _shape = characterize(3)
        stored.clear()
        assert holder.func_name == holder3.func_name
        assert holder.func_name not in synthesized, synthesized
        assert holder.delay == 50, holder.delay  # fake_measured's, not 10 ns derived
        # A different shape (no evidence) is synthesized again.
        MCP.ISOLATED_MCP_EVIDENCE.clear()
        _ps, holder, _shape = characterize(3)
        assert holder.func_name in synthesized


def test_jobs_cap_covers_mcp_characterization():
    """-j N bounds every synthesis pool. Pre-pipelining characterization of
    both MCP holders and the AUTO_PIPELINE side shares one pool: -j 1 runs one
    backend process at a time, -j 3 overlaps them (so the probe can see
    concurrency). Every compiler ThreadPool is sized by GET_NUM_PROCESSES, and
    an invalid count stops pypelinec before it parses or creates anything."""
    import re
    import subprocess
    import threading
    import time
    import pypeline

    lock = threading.Lock()
    active, peak, synthesized = [0], [0], []

    def fake_syn(inst, logic, ps, tpl, *a, **k):
        SYN.REUSE_ONLY_MISS()  # the backend contract: a lookup never runs
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            synthesized.append(logic.func_name)
        time.sleep(0.05)
        with lock:
            active[0] -= 1
        return logic.func_name

    def fake_measured(logic, report, ps):
        logic.delay = 50
        logic.delay_is_estimated = False

    def characterize(jobs):
        peak[0] = 0
        synthesized.clear()
        with tempfile.TemporaryDirectory() as out, patch.object(SYN, "SYN_OUTPUT_DIRECTORY", out), \
                patch.object(MCP, "ISOLATED_MCP_EVIDENCE", {}):
            pypeline.SET_AUTO_MULTI_CYCLE_LATENCY_CACHE({})
            ps = PY_TO_LOGIC.PARSE_FILE(str(Path(__file__).with_name("added_latency_context_design.py")))
            with patch.object(SYN, "SYN_TOOL", SimpleNamespace(SYN_AND_REPORT_TIMING=fake_syn, __name__="FAKE")), \
                    patch.object(SYN, "PART_SET_TOOL", lambda *a, **k: None), \
                    patch.object(SYN, "WRITE_BLACK_BOX_FILES", lambda *a, **k: None), \
                    patch.object(SYN, "GET_CACHED_PATH_DELAY", lambda *a: None), \
                    patch.object(SYN, "NUM_PROCESSES", jobs), \
                    patch.object(SYN, "SET_MEASURED_DELAY_FROM_REPORT", fake_measured), \
                    patch.object(SYN.DEVICE_MODELS, "part_supported", lambda part: False):
                SYN.ADD_PATH_DELAY_TO_LOOKUP(ps)
        return ps

    ps = characterize(1)
    holders = {logic.func_name for logic in _holders(ps).values()}
    assert len(holders) == 2, holders
    assert holders <= set(synthesized), (holders, synthesized)
    assert len(set(synthesized) - holders) >= 2, synthesized
    assert peak[0] == 1, f"-j 1 ran {peak[0]} syntheses at once"
    characterize(3)
    assert 1 < peak[0] <= 3, f"-j 3 peak concurrency {peak[0]}"

    # Every pool in the compiler is sized by the one -j knob.
    src = Path(SYN.__file__).parent
    pools = []
    for path in sorted(src.glob("*.py")):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if re.search(r"\b(ThreadPool|ThreadPoolExecutor|ProcessPoolExecutor|Pool)\(", line) \
                    and not line.lstrip().startswith(("#", "from ", "import ")):
                pools.append((path.name, number, line.strip()))
    assert pools, "no synthesis pools found: the audit is checking nothing"
    # pypeline_sim_debug runs its native and VHDL simulations side by side
    # from one warm build; neither synthesizes.
    unbounded = [
        p for p in pools
        if "GET_NUM_PROCESSES()" not in p[2] and p[0] != "pypeline_sim_debug.py"
    ]
    assert not unbounded, unbounded

    pypelinec = src / "pypelinec"
    design = Path(__file__).with_name("added_latency_context_design.py")
    for bad in ("0", "-2"):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "out"
            result = subprocess.run(
                [sys.executable, str(pypelinec), str(design), "--jobs", bad,
                 "--out_dir", str(out), "--no_synth"],
                capture_output=True, text=True, timeout=300,
            )
            assert result.returncode != 0, result.stdout[-2000:]
            assert f"--jobs must be at least 1, got {bad}" in result.stderr, result.stderr[-2000:]
            assert "PY_TO_LOGIC parsing" not in result.stdout, result.stdout[-2000:]
            assert not out.exists(), sorted(p.name for p in out.iterdir())


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



def test_mcp_endpoint_attributes_and_cache_identity():
    ps = _state()
    tpl = _empty(ps)
    mtp = AP.MultiMainTimingParams()
    mtp.TimingParamsLookupTable = tpl
    hashes = {i: tp.GET_HASH_EXT(tpl, ps) for i, tp in tpl.items()}
    top_hash = mtp.GET_HASH_EXT(ps)
    with patch.object(MCP, "MCP_IMPLEMENTATION_VERSION", MCP.MCP_IMPLEMENTATION_VERSION + 1):
        updated = _empty(ps)
        for inst, tp in updated.items():
            contains_mcp = any(_under(holder, inst) for holder in _holders(ps))
            assert (tp.GET_HASH_EXT(updated, ps) != hashes[inst]) == contains_mcp, inst
        mtp.TimingParamsLookupTable = updated
        assert mtp.GET_HASH_EXT(ps) != top_hash
    mtp.TimingParamsLookupTable = tpl
    assert mtp.GET_HASH_EXT(ps) == top_hash  # warm identity is stable
    fixed_holder, fixed_logic = next((i, l) for i, l in _holders(ps).items() if not l.auto_multi_cycle_tuples)
    changed_tuples = {(str(int(n) + 1), start, end) for n, start, end in fixed_logic.mcp_tuples}
    with patch.object(fixed_logic, "mcp_tuples", changed_tuples):
        updated = _empty(ps)
        for inst, tp in updated.items():
            assert (tp.GET_HASH_EXT(updated, ps) != hashes[inst]) == _under(fixed_holder, inst), inst
    with tempfile.TemporaryDirectory() as out:
        for inst, logic in _holders(ps).items():
            VHDL.WRITE_LOGIC_ENTITY(inst, logic, out, ps, tpl)
            entity = VHDL.GET_ENTITY_NAME(inst, logic, tpl, ps)
            text = Path(out, entity + ".vhd").read_text()
            assert text.count("attribute dont_touch : string;") == 1
            for reg in MCP.MCP_ENDPOINT_REGS(logic):
                name = VHDL.WIRE_TO_VHDL_NAME(reg, logic)
                assert f'attribute dont_touch of {name} : signal is "true";' in text
            assert text.count("attribute dont_touch of ") == 2
        # A shared helper's AUTO_PIPELINE instance receives no MCP attributes.
        body = next(i for i in _insts(ps, "helper") if AP.ADDED_LATENCY_BLOCKER(i, ps) is None)
        logic = ps.LogicInstLookupTable[body]
        VHDL.WRITE_LOGIC_ENTITY(body, logic, out, ps, tpl)
        text = Path(out, VHDL.GET_ENTITY_NAME(body, logic, tpl, ps) + ".vhd").read_text()
        assert "attribute dont_touch" not in text


def test_mcp_constraints_and_lost_coverage_diagnostics():
    ps = _state()
    tpl = _empty(ps)
    mtp = AP.MultiMainTimingParams()
    mtp.TimingParamsLookupTable = tpl
    mtp.auto_multi_cycle_ncycles = MCP.ELABORATED_AUTO_MULTI_CYCLE_NCYCLES(ps)
    for holder, logic in _holders(ps).items():
        main = C_TO_LOGIC.RECURSIVE_FIND_MAIN_FUNC_FROM_INST(holder, ps)
        top = VHDL.GET_ENTITY_NAME(main, ps.LogicInstLookupTable[main], tpl, ps)
        tup, start, end, auto = MCP.GET_MCP_CELL_PATHS(holder, main, top, ps)[0]
        for count in (1, 4):
            replacement = {(str(count), tup[1], tup[2])}
            overrides = {auto.key: count} if auto else {}
            with patch.object(logic, "mcp_tuples", replacement), patch.object(mtp, "auto_multi_cycle_ncycles", overrides), patch.object(SYN, "SYN_TOOL", VIVADO):
                xdc = "\n".join(MCP.GET_MCP_PATH_CONSTRAINTS(holder, main, top, mtp, ps))
                assert f"set_multicycle_path {count} -setup" in xdc
                assert f"set_multicycle_path {count - 1} -hold" in xdc
                assert xdc.count(f"[get_pins {{{start}/C}}]") == 2
                assert xdc.count(f"[get_pins {{{end}/D}}]") == 2
                assert xdc.count("set_property DONT_TOUCH TRUE") == 2
                report = SimpleNamespace(
                    start_reg_name=start.replace("[*]", "[3]"),
                    end_reg_name=end.replace("[*]", "[7]"),
                    start_pin_name="C", end_pin_name="D", start_cell_type="FDRE",
                    source_ns_per_clock=12.5, requirement_ns=count * 12.5,
                )
                timing = SimpleNamespace(path_reports={"clk": report})
                MCP.CHECK_MCP_TIMING_REPORT(timing, ps, mtp)
                if auto:
                    group = MCP.AUTO_MULTI_CYCLE_GROUP_FOR_PATH_REPORT(report, MCP.COLLECT_AUTO_MULTI_CYCLE_GROUPS(ps), ps, mtp)
                    assert group is not None and group.key == auto.key
                report.requirement_ns = (count + 1) * 12.5
                try:
                    MCP.CHECK_MCP_TIMING_REPORT(timing, ps, mtp)
                except ValueError as err:
                    assert "MCP timing coverage error" in str(err) and holder in str(err)
                else:
                    raise AssertionError("wrong setup requirement accepted")
                report.end_pin_name = "CE"
                MCP.CHECK_MCP_TIMING_REPORT(timing, ps, mtp)
                assert MCP.AUTO_MULTI_CYCLE_GROUP_FOR_PATH_REPORT(report, MCP.COLLECT_AUTO_MULTI_CYCLE_GROUPS(ps), ps, mtp) is None
                report.end_pin_name = "D"
                # Reproduce the DSP-origin report with a real combinational
                # descendant; endpoints alone still partially match the XDC.
                interior = next(i for i in _insts(ps, "helper") if _under(i, holder))
                suffix = interior[len(holder + M):].split(M)
                dsp = end.rsplit("/", 1)[0] + "/" + "/".join(VHDL.WIRE_TO_VHDL_NAME(x, ps) for x in suffix) + "/return_output0__55"
                report.start_reg_name = dsp
                report.start_pin_name = "CLK"
                report.start_cell_type = "DSP48E1"
                report.requirement_ns = 12.5
                try:
                    MCP.CHECK_MCP_TIMING_REPORT(timing, ps, mtp)
                except ValueError as err:
                    assert "sequential DSP" in str(err) and "expected" in str(err)
                else:
                    raise AssertionError("escaped DSP endpoint accepted")
                # A different hierarchy or an explicitly pipelined descendant
                # is not evidence of lost MCP coverage.
                report.start_reg_name = "unrelated/dsp"
                MCP.CHECK_MCP_TIMING_REPORT(timing, ps, mtp)
                report.start_reg_name = dsp
                local = suffix[0]
                tags = dict(logic.sub_inst_to_auto_pipeline_latency)
                tags[local] = C_TO_LOGIC.AutoPipelineLatency()
                with patch.object(logic, "sub_inst_to_auto_pipeline_latency", tags):
                    MCP.CHECK_MCP_TIMING_REPORT(timing, ps, mtp)

if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
