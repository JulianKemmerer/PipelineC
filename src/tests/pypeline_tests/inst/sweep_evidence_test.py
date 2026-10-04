#!/usr/bin/env python3
"""Sweep implementation identity, concrete replay and backend evidence contracts."""

import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))
import AUTO_PIPELINE
import SWEEP
import SYN
import VIVADO
from typed_pipeline_placement_test import FakeLogic, FakeParserState


def test_concrete_lock_replays_identical_descendants_after_model_refresh():
    marker = SWEEP.C_TO_LOGIC.SUBMODULE_MARKER
    root = FakeLogic("helper")
    mul = FakeLogic("mul")
    add = FakeLogic("add")
    reducer = FakeLogic("reducer")
    root.submodule_instances = {"m": "mul", "a": "add", "r": "reducer"}
    ps = FakeParserState(
        {
            "main": root,
            "main" + marker + "m": mul,
            "main" + marker + "a": add,
            "main" + marker + "r": reducer,
        }
    )
    table = {
        i: AUTO_PIPELINE.TimingParams(i, l) for i, l in ps.LogicInstLookupTable.items()
    }
    for local, cycles in [("m", 1), ("a", 1), ("r", 4)]:
        table["main" + marker + local].SET_SLICES(
            [(n + 1) / (cycles + 1) for n in range(cycles)]
        )
    expected = table["main"].GET_HASH_EXT(table, ps)
    snapshot = AUTO_PIPELINE.CAPTURE_CONCRETE_PIPELINE("main", table, ps)
    old_model = SWEEP.SUBTREE_MODEL_FINGERPRINT("main", ps)
    reducer.delay = 10000
    assert old_model != SWEEP.SUBTREE_MODEL_FINGERPRINT("main", ps)
    fresh = {
        i: AUTO_PIPELINE.TimingParams(i, l) for i, l in ps.LogicInstLookupTable.items()
    }
    plan = SWEEP.MainSweepPlan("main", 80)
    plan.locked["main"] = SWEEP.MiniSweepLock(
        [0.2, 0.4, 0.6, 0.8],
        concrete=snapshot,
        model_fingerprint=old_model,
        winner_hash=expected,
    )
    from unittest.mock import patch

    with patch.object(AUTO_PIPELINE, "CHECK_ADDED_LATENCY_CONTEXT"), patch.object(
        SWEEP, "APPLY_PIPELINE_PLACEMENTS", side_effect=lambda _, ps, t: t
    ), patch.object(
        AUTO_PIPELINE,
        "ADD_SLICES_DOWN_HIERARCHY_TIMING_PARAMS_AND_WRITE_VHDL_PACKAGES",
        side_effect=AssertionError("fractional replay"),
    ):
        SWEEP.APPLY_LOCKS(plan, ps, fresh)
    assert fresh["main"].GET_HASH_EXT(fresh, ps) == expected
    assert [len(fresh["main" + marker + x]._slices) for x in ("m", "a", "r")] == [
        1,
        1,
        4,
    ]


def test_input_identity_follows_tool_inputs_not_location_or_provenance():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        manifests = []
        for name in ("a", "b"):
            p = root / name
            p.mkdir()
            (p / "logic.vhd").write_text("entity logic is end;")
            (p / "clock.xdc").write_text("create_clock -period 10 [get_ports clk]")
            tcl = f"read_vhdl -vhdl2008 -library work {{{p}/logic.vhd}}\nread_xdc {{{p}/clock.xdc}}\nwrite_checkpoint {p}/top.dcp\n"
            manifests.append(VIVADO.INPUT_MANIFEST(tcl, "part", "2019.2", p))
        assert manifests[0]["signature"] == manifests[1]["signature"]
        (p / "clock.xdc").write_text("create_clock -period 25 [get_ports clk]")
        changed = VIVADO.INPUT_MANIFEST(tcl, "part", "2019.2", p)
        assert changed["signature"] != manifests[1]["signature"]
        assert (
            VIVADO.INPUT_MANIFEST(tcl + "report_timing\n", "part", "2019.2", p)[
                "signature"
            ]
            != changed["signature"]
        )


def test_requested_overflow_survives_final_table_at_capacity():
    header = "| Site Type | Used | Fixed | Available | Util% |\n"
    text = (
        "WARNING: [Synth 8-3323] Resources of type DSP have been overutilized. Used = 768, Available = 740.\n"
        + header
        + "| DSPs | 740 | 0 | 740 | 100.00 |\n"
    )
    report = VIVADO.PARSE_UTILIZATION(text)
    assert report["status"] == "over_capacity"
    assert report["resources"]["DSPs"]["used"] == 740
    assert report["overutilization"][0]["used"] == 768
    assert (
        VIVADO.PARSE_UTILIZATION(text.replace("DSP", "LUT"))["status"]
        == "over_capacity"
    )
    assert VIVADO.PARSE_UTILIZATION("")["status"] == "unknown"
    # Verbatim from the shared WireGuard 70 MHz confirmation (latency-sized
    # MAC lanes C=7): Vivado remaps the excess into LUTs and its table caps
    # at the device's 740, but the requested 960 is the fit evidence.
    real = (
        "WARNING: [Synth 8-3323] Resources of type DSP have been overutilized. "
        "Used = 960, Available = 740. Use report_utilization command for details.\n"
        + header
        + "| DSPs | 740 | 0 | 740 | 100.00 |\n"
    )
    report = VIVADO.PARSE_UTILIZATION(real)
    assert report["status"] == "over_capacity"
    assert report["resources"]["DSPs"]["used"] == 740
    assert report["overutilization"][0]["used"] == 960
    assert report["overutilization"][0]["available"] == 740


def test_utilization_tables_are_read_by_header_columns():
    # Vivado 2019.2 (5 columns) and newer releases (extra Prohibited column).
    old = "| Site Type | Used | Fixed | Available | Util% |\n| DSPs | 512 | 0 | 740 | 69.19 |\n"
    new = "| Site Type | Used | Fixed | Prohibited | Available | Util% |\n| DSPs | 800 | 0 | 0 | 740 | 108.11 |\n"
    assert VIVADO.PARSE_UTILIZATION(old)["resources"]["DSPs"] == dict(used=512, available=740)
    report = VIVADO.PARSE_UTILIZATION(new)
    assert report["resources"]["DSPs"] == dict(used=800, available=740)
    assert report["status"] == "over_capacity"
    # Rows under other tables (e.g. primitives) are never read as capacity.
    other = "| Ref Name | Used | Functional Category |\n| DSP48E1 | 740 | Block Arithmetic |\n"
    assert VIVADO.PARSE_UTILIZATION(other)["status"] == "unknown"


def test_bank_dedup_keeps_fields_and_pipeline_stage():
    bank = SYN.PATH_REGISTER_BANK
    assert bank("m/reg[field][2][17]") == bank("m/reg[field][7][22]")
    assert bank("m/reg[field][17]") != bank("m/reg[other][17]")
    assert bank("m/reg[raw_hdl_pipeline][1][return_output][45]") != bank(
        "m/reg[raw_hdl_pipeline][2][return_output][45]"
    )
    paths = [
        SimpleNamespace(
            start_reg_name="m/launch[%d]" % i,
            end_reg_name="m/capture[%d]" % i,
            path_group="clk",
            slack_ns=-i,
        )
        for i in range(649)
    ]
    groups = SYN.DISTINCT_PATHS(paths)
    assert (
        len(groups) == 1
        and groups[0]["member_count"] == 649
        and groups[0]["path"].slack_ns == -648
    )


def test_incomplete_and_errored_logs_are_not_accepted():
    for content in [
        "",
        "Exiting Vivado",
        "ERROR: failed\nPYPELINEC_SYNTHESIS_COMPLETE\n",
    ]:
        try:
            VIVADO.REQUIRE_COMPLETE_LOG(content, "preserve.log")
        except RuntimeError as error:
            assert "No automatic rerun" in str(error)
        else:
            raise AssertionError("accepted incomplete or errored log")
    VIVADO.REQUIRE_COMPLETE_LOG("PYPELINEC_SYNTHESIS_COMPLETE\n", "ok.log")
    # A place-and-route failure on an over-capacity design names the overflow.
    try:
        VIVADO.REQUIRE_COMPLETE_LOG(
            "WARNING: [Synth 8-3323] Resources of type DSP have been overutilized. "
            "Used = 768, Available = 740.\nERROR: [Place 30-640] Place Check\n",
            "pnr.log",
        )
    except RuntimeError as error:
        assert "DOES NOT FIT: requested DSP 768/740" in str(error), str(error)
        assert "No automatic rerun" in str(error)
    else:
        raise AssertionError("accepted an errored place-and-route log")


def test_optional_compact_paths_preserve_mcp_normalization_and_coverage():
    import VIVADO

    paths, coverage = VIVADO.PARSE_EXTRA_PATHS(
        "PYPELINEC_COVERAGE\tfailing\t4096\t4096\n"
        "PYPELINEC_PATH\tmcp:holder:launch:capture\tclk\t-7.357\t50\t57.311\t198\t25\tm/launch[4]/C\tm/capture[4]/D\tFDRE\tFDRE\n"
    )
    assert len(paths) == 1 and abs(paths[0].path_delay_ns - 28.6785) < 1e-6
    assert paths[0].requirement_ns - paths[0].slack_ns == 57.357
    assert coverage["failing"]["truncated"] and not coverage["failing"]["complete"]
    assert VIVADO.PARSE_EXTRA_PATHS("legacy report") == ([], {})


def test_mcp_seed_uses_raw_endpoint_evidence_and_honors_caps():
    import AUTO_MULTI_CYCLE as mcp
    from unittest.mock import patch

    groups = {}
    logic = FakeLogic(
        "holder", wire_to_c_type={"launch": "uint32_t", "capture": "uint32_t"}
    )
    logic.submodule_instances = {"body": "arithmetic_shape"}
    ps = FakeParserState({"a": logic, "b": logic})
    for name in ("a", "b"):
        group = mcp.AutoMultiCycleGroup(
            name, SWEEP.C_TO_LOGIC.AutoMultiCycleConstraint(name)
        )
        group.paths = [(name, "launch", "capture")]
        groups[name] = group
    params = SimpleNamespace(auto_multi_cycle_ncycles={})
    evidence = {
        (key, mcp.MCP_SHAPE(group, ps)): delay
        for (key, group), delay in zip(groups.items(), (57.8, 45.0))
    }
    with patch.object(
        mcp, "COLLECT_AUTO_MULTI_CYCLE_GROUPS", return_value=groups
    ), patch.object(mcp, "ISOLATED_MCP_EVIDENCE", evidence), patch.object(
        mcp, "PROVISIONAL_MCP_SEEDS", {}
    ), patch.object(
        mcp, "ELABORATED_AUTO_MULTI_CYCLE_NCYCLES", return_value={"a": 2, "b": 1}
    ), patch.object(SWEEP.SYN, "GET_TARGET_MHZ", return_value=40), patch.object(
        SWEEP.C_TO_LOGIC,
        "RECURSIVE_FIND_MAIN_FUNC_FROM_INST",
        side_effect=lambda i, p: i,
    ):
        assert mcp.SEED_COUNTS(ps, params) == {"a": 3, "b": 2}
        groups["a"].constraint.max_latency = 2
        params.auto_multi_cycle_ncycles = {}
        assert mcp.SEED_COUNTS(ps, params) == {"a": 2, "b": 2}


def test_fit_stop_records_evidence_before_any_timing_feedback():
    from unittest.mock import patch
    import SYN

    logic = FakeLogic("main")
    ps = FakeParserState({"main": logic})
    ps.main_mhz = {"main": 40}
    table = {"main": AUTO_PIPELINE.TimingParams("main", logic)}
    params = SimpleNamespace(TimingParamsLookupTable=table, auto_multi_cycle_ncycles={})
    report = SimpleNamespace(
        path_reports={},
        utilization=VIVADO.PARSE_UTILIZATION(
            "Resources of type DSP have been overutilized. Used = 768, Available = 740."
        ),
    )
    with patch.object(SYN, "GET_TARGET_MHZ", return_value=40), patch.object(
        SWEEP, "STOP_ON_OVER_CAPACITY", True
    ), patch.object(SWEEP, "SYNTHESIS_OBSERVATIONS", []), patch.object(
        SWEEP, "SWEEP_OUTCOMES", {}
    ), patch.object(SWEEP, "WRITE_SWEEP_HISTORY") as writer:
        try:
            SWEEP.RECORD_SYNTHESIS_OBSERVATION(ps, params, report, 1)
        except SystemExit as error:
            assert "DOES NOT FIT" in str(error)
        else:
            raise AssertionError("fit stop failed")
        assert writer.call_count == 1
        assert params.sweep_timing_failures[0][2] is None
        assert (
            SWEEP.SYNTHESIS_OBSERVATIONS[0]["utilization"]["status"] == "over_capacity"
        )


def test_region_latency_changes_survive_renamed_wrappers():
    """The 40 MHz fit-stop record showed previous: null for the Poly1305
    bodies because re-elaboration renamed their lane wrappers. Region depths
    are keyed by owning MAIN and canonical key; physical paths are evidence."""
    from unittest.mock import patch
    import SYN

    M = SWEEP.C_TO_LOGIC.SUBMODULE_MARKER

    def observe(wrapper, depth):
        ps = FakeParserState({"m": FakeLogic("m"), "m" + M + wrapper: FakeLogic(wrapper),
                              "m" + M + wrapper + M + "core": FakeLogic("core")})
        ps.LogicInstLookupTable["m" + M + wrapper].sub_inst_to_auto_pipeline_key = {"core": "body_key"}
        ps.main_mhz = {"m": 40}
        tp = lambda n: SimpleNamespace(GET_TOTAL_LATENCY=lambda *a: n)
        table = {"m": tp(depth + 2), "m" + M + wrapper: tp(depth), "m" + M + wrapper + M + "core": tp(depth)}
        params = SimpleNamespace(TimingParamsLookupTable=table, auto_multi_cycle_ncycles={})
        report = SimpleNamespace(path_reports={}, utilization=dict(status="within_reported_limits", resources={}, overutilization=[]))
        return SWEEP.RECORD_SYNTHESIS_OBSERVATION(ps, params, report, 1)

    with patch.object(SYN, "GET_TARGET_MHZ", return_value=40), patch.object(
        SWEEP, "SYNTHESIS_OBSERVATIONS", []
    ), patch.object(SWEEP, "IMPLEMENTATION_SIGNATURE", return_value="sig"):
        observe("lanes_2", 0)
        second = observe("lanes_5", 3)
    key = "AUTO_PIPELINE:m:body_key"
    assert second["latency_changes_since_fit"][key] == dict(previous=0, current=3), second["latency_changes_since_fit"]
    assert second["auto_pipeline_instances"][key] == ["m" + M + "lanes_5" + M + "core"]


def test_scripted_shared_clock_freezes_unimplicated_and_skips_noops():
    from unittest.mock import patch
    from contextlib import ExitStack
    from scripted_sweep_backend import ScriptedBackend, path
    import SYN

    marker = SWEEP.C_TO_LOGIC.SUBMODULE_MARKER

    def run(order, multiple):
        # Each MAIN holds one helper; like the real mini-sweep, the lock is on
        # the helper, never on the MAIN/subtree root (see LOCK_BLOCKED_REASON).
        insts = {}
        for m in order:
            main = FakeLogic(m)
            main.submodule_instances = {"h": "h_" + m}
            insts[m] = main
            insts[m + marker + "h"] = FakeLogic("h_" + m)
        ps = FakeParserState(insts)
        ps.main_mhz = {m: 100 for m in order}
        ps.FuncToInstances = {l.func_name: {i} for i, l in insts.items()}
        for logic in ps.LogicInstLookupTable.values():
            logic.delay = 200
            logic.delay_is_estimated = False
        helper = {m: m + marker + "h" for m in order}

        def fresh(_):
            return {
                i: AUTO_PIPELINE.TimingParams(i, l)
                for i, l in ps.LogicInstLookupTable.items()
            }

        params = SimpleNamespace(
            TimingParamsLookupTable=fresh(ps), auto_multi_cycle_ncycles={}
        )
        built = []

        def rule(ps, params):
            cuts = {m: len(params.TimingParamsLookupTable[helper[m]]._slices) for m in order}
            built.append(cuts)
            return [
                path(m, 15 if m != "quiet" and cuts[m] == 0 else 5)
                for m in sorted(order)
            ]

        backend = ScriptedBackend(rule, multiple)

        def landscape(root, *args):
            view = SWEEP.SliceLandscape(root, 20, 0.1)
            view.finalize({})
            return view

        def mini(func, plan, ps):
            table = fresh(ps)
            target = helper[plan.main_inst]
            table[target].SET_SLICES([0.5])
            plan.locked[target] = SWEEP.MiniSweepLock(
                [0.5],
                concrete=AUTO_PIPELINE.CAPTURE_CONCRETE_PIPELINE(target, table, ps),
                model_fingerprint=SWEEP.SUBTREE_MODEL_FINGERPRINT(target, ps),
            )
            return True

        noop = lambda *a, **k: None
        with tempfile.TemporaryDirectory() as out, ExitStack() as stack:
            patches = [
                (SYN, "SYN_TOOL", backend),
                (SYN, "SYN_OUTPUT_DIRECTORY", out),
                (SYN, "GET_TARGET_MHZ", lambda m, p: 100),
                (SYN, "LOGIC_IS_ZERO_DELAY", lambda *a, **k: False),
                (SYN, "WRITE_REGISTERS_ESTIMATE_FILE", noop),
                (SYN, "WRITE_AREA_ESTIMATE_FILE", noop),
                (SYN, "ESTIMATE_DESIGN_AREA", lambda *a: {"total_area": 0}),
                (SYN, "PRINT_MEASURED_AREA_IF_AVAILABLE", noop),
                (SYN, "FUNC_SRC_LOC_STR", lambda *a: ""),
                (AUTO_PIPELINE, "GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP", fresh),
                (AUTO_PIPELINE, "COLLECT_AUTO_PIPELINE_REGIONS", lambda *a: []),
                (AUTO_PIPELINE, "CHECK_ADDED_LATENCY_CONTEXT", noop),
                (AUTO_PIPELINE, "WRITE_ALL_NON_ZERO_CLK_VHDL_FILES", noop),
                (
                    AUTO_PIPELINE,
                    "INVALIDATE_MODIFIED_INST_ANCESTOR_CACHES",
                    lambda *a: set(),
                ),
                (AUTO_PIPELINE, "CHECK_AUTO_PIPELINE_CONSTRAINTS_REALIZED", noop),
                (AUTO_PIPELINE, "ADDED_LATENCY_BLOCKER", lambda *a: None),
                (
                    AUTO_PIPELINE.TimingParams,
                    "GET_TOTAL_LATENCY",
                    lambda self, _ps, t: sum(
                        len(t[i]._slices)
                        for i in t
                        if i == self.inst_name or i.startswith(self.inst_name + marker)
                    ),
                ),
                (
                    AUTO_PIPELINE,
                    "FUNC_HAS_HIER_ALLOWING_ADDED_LATENCY_TO_RAW_VHDL",
                    lambda *a: True,
                ),
                (SWEEP, "COLLECT_CUT_SUBTREES", lambda m, p: [m]),
                (SWEEP, "BUILD_SLICE_LANDSCAPE", landscape),
                (SWEEP, "PLAN_PIPELINE_PLACEMENTS", lambda *a, **k: ([], [])),
                (
                    SWEEP,
                    "RESOLVE_PIPELINABLE_HOTSPOT",
                    lambda path, plan, ps: ("h_" + plan.main_inst, None, ""),
                ),
                (SWEEP, "RUN_HOTSPOT_MINISWEEP", mini),
                (SWEEP, "RUN_AS_WRITTEN_CHECKS", lambda *a: {}),
                (
                    SWEEP,
                    "GET_MAIN_INSTS_FOR_PATH_REPORT",
                    lambda p, *a: {p.start_reg_name.split("/")[0]},
                ),
                (
                    SWEEP,
                    "SUMMARIZE_SUBTREE_PIPELINE",
                    lambda m, st, t, p: (False, [], len(t[helper[m]]._slices)),
                ),
                (
                    SWEEP,
                    "GET_SUBTREE_PIPELINE_STAGES",
                    lambda plan, t, p: len(t[helper[plan.main_inst]]._slices),
                ),
                (SWEEP, "WRITE_PIPELINE_PLACEMENT_TRACE", noop),
                (SWEEP, "WRITE_SWEEP_HISTORY", noop),
                (SWEEP, "LOAD_INTERNAL_PLACEMENT_CONFIG", lambda: None),
                (SWEEP, "PRINT_FLOOR_REPORT", noop),
                (SWEEP, "SWEEP_HISTORY", {}),
                (SWEEP, "SWEEP_OUTCOMES", {}),
                (SWEEP, "SYNTHESIS_OBSERVATIONS", []),
                (SWEEP, "CARRIED_LOCKS", {}),
                (SWEEP, "PIPELINE_MIN_EFFORT", 0),
            ]
            for obj, key, value in patches:
                stack.enter_context(patch.object(obj, key, value))
            result = SWEEP.DO_PLANNED_THROUGHPUT_SWEEP(ps, params)
            assert not result.sweep_timing_failures, result.sweep_timing_failures
            assert all(row["quiet"] == 0 for row in built), built
            assert all(
                len(result.TimingParamsLookupTable[helper[m]]._slices) == 1
                for m in ("a", "b")
            )
            # The initial densify realizes no change, so the mini-sweep ladder
            # consumes the same observation instead of asking the backend again.
            attempts = max(
                r["iter"]
                for records in SWEEP.SWEEP_HISTORY.values()
                for r in records["iterations"]
            )
            assert attempts > len(backend.calls)
            hashes = {
                m: result.TimingParamsLookupTable[m].GET_HASH_EXT(
                    result.TimingParamsLookupTable, ps
                )
                for m in order
            }
            # A fresh re-elaboration gets the same concrete locks without
            # rediscovering them. No stale Logic object is carried over.
            second = ScriptedBackend(rule, multiple)
            params2 = SimpleNamespace(
                TimingParamsLookupTable=fresh(ps), auto_multi_cycle_ncycles={}
            )
            with patch.object(SYN, "SYN_TOOL", second), patch.object(
                SWEEP,
                "RUN_HOTSPOT_MINISWEEP",
                side_effect=AssertionError("lock rediscovered"),
            ):
                result2 = SWEEP.DO_PLANNED_THROUGHPUT_SWEEP(ps, params2)
            assert len(second.calls) == 1
            assert hashes == {
                m: result2.TimingParamsLookupTable[m].GET_HASH_EXT(
                    result2.TimingParamsLookupTable, ps
                )
                for m in order
            }
            return len(backend.calls), hashes, built, backend.calls

    single = run(["quiet", "a", "b"], False)
    multi = run(["quiet", "a", "b"], True)
    reversed_multi = run(["b", "a", "quiet"], True)
    assert multi[0] < single[0]
    assert multi == reversed_multi
    import json

    print(
        "TRAJECTORIES " + json.dumps(dict(single=single, multi=multi), sort_keys=True)
    )


def test_mcp_only_confirmation_repairs_all_groups_in_one_feedback_round():
    from unittest.mock import patch
    from contextlib import ExitStack
    from scripted_sweep_backend import ScriptedBackend, path
    import SYN, VHDL, AUTO_MULTI_CYCLE as mcp

    ps = FakeParserState({m: FakeLogic(m) for m in ("a", "b", "quiet")})
    ps.main_mhz = {m: 100 for m in ps.LogicInstLookupTable}
    ps.part = "scripted"
    table = {
        m: AUTO_PIPELINE.TimingParams(m, l) for m, l in ps.LogicInstLookupTable.items()
    }
    for tp in table.values():
        tp.SET_SLICES([0.3, 0.7])
    params = SimpleNamespace(
        TimingParamsLookupTable=table, auto_multi_cycle_ncycles={"a": 1, "b": 1}
    )
    hashes = {m: t.GET_HASH_EXT(table, ps) for m, t in table.items()}
    groups = {
        m: mcp.AutoMultiCycleGroup(m, SWEEP.C_TO_LOGIC.AutoMultiCycleConstraint(m))
        for m in ("a", "b")
    }

    def rule(ps, params):
        rows = []
        for main, raw in (("a", 21.0), ("b", 31.0)):
            n = params.auto_multi_cycle_ncycles[main]
            row = path(main, raw / n)
            row.requirement_ns = n * 10
            row.slack_ns = n * 10 - raw
            rows.append(row)
        rows.append(path("quiet", 5))
        return rows

    backend = ScriptedBackend(rule, True)
    noop = lambda *a, **kw: None
    with ExitStack() as stack:
        patches = [
            (SYN, "SYN_TOOL", backend),
            (SYN, "PART_SET_TOOL", noop),
            (SYN, "GET_TARGET_MHZ", lambda m, p: 100),
            (SYN, "LOGIC_IS_ZERO_DELAY", lambda *a, **kw: False),
            (SYN, "WRITE_BLACK_BOX_FILES", noop),
            (SYN, "WRITE_REGISTERS_ESTIMATE_FILE", noop),
            (SYN, "WRITE_AREA_ESTIMATE_FILE", noop),
            (SYN, "ESTIMATE_DESIGN_AREA", lambda *a: {"total_area": 0}),
            (SYN, "PRINT_MEASURED_AREA_IF_AVAILABLE", noop),
            (VHDL, "WRITE_CLK_CROSS_ENTITIES", noop),
            (VHDL, "WRITE_MULTIMAIN_TOP", noop),
            (
                AUTO_PIPELINE,
                "INVALIDATE_MODIFIED_INST_ANCESTOR_CACHES",
                lambda *a: set(),
            ),
            (AUTO_PIPELINE, "WRITE_ALL_NON_ZERO_CLK_VHDL_FILES", noop),
            (SWEEP, "COLLECT_CUT_SUBTREES", lambda *a: []),
            (SWEEP, "RECORD_CONFIRMATION_RESULTS", noop),
            (SWEEP, "SYNTHESIS_OBSERVATIONS", []),
            (
                SWEEP,
                "GET_MAIN_INSTS_FOR_PATH_REPORT",
                lambda p, *a: {p.start_reg_name.split("/")[0]},
            ),
            (
                SWEEP,
                "DO_PLANNED_THROUGHPUT_SWEEP",
                lambda *a: (_ for _ in ()).throw(
                    AssertionError("MCP failure restarted placement")
                ),
            ),
            (mcp, "COLLECT_AUTO_MULTI_CYCLE_GROUPS", lambda p: groups),
            (mcp, "SEED_COUNTS", noop),
            (mcp, "PROPOSE_CONFIRM_DOWN", lambda *a: {}),
            (
                mcp,
                "AUTO_MULTI_CYCLE_GROUP_FOR_PATH_REPORT",
                lambda path, *a: groups.get(path.start_reg_name.split("/")[0]),
            ),
        ]
        for obj, name, value in patches:
            stack.enter_context(patch.object(obj, name, value))
        result, met = SWEEP.DO_SEEDED_CONFIRM_OR_SWEEP(ps, params)
        assert met and not result.sweep_timing_failures
        assert result.auto_multi_cycle_ncycles == {"a": 3, "b": 4}
        assert len(backend.calls) == 2
        assert hashes == {m: t.GET_HASH_EXT(table, ps) for m, t in table.items()}


def test_locked_internal_endpoints_skip_boundary_policies():
    from unittest.mock import patch
    import VHDL

    marker = SWEEP.C_TO_LOGIC.SUBMODULE_MARKER
    ps = FakeParserState(
        {"main": FakeLogic("main"), "main" + marker + "hot": FakeLogic("hot")}
    )
    plan = SWEEP.MainSweepPlan("main", 80)
    plan.locked["main" + marker + "hot"] = SWEEP.MiniSweepLock([0.5])
    path = SimpleNamespace(
        start_reg_name="main_entity/hot/mul/register_a[0]",
        end_reg_name="main_entity/hot/mul/register_b[0]",
    )
    with patch.object(VHDL, "GET_ENTITY_NAME", return_value="main_entity"):
        assert SWEEP.PATH_INSIDE_LOCK(path, plan, ps, {})
        path.start_reg_name = "main_entity/hot/input_regs[0]"
        assert not SWEEP.PATH_INSIDE_LOCK(path, plan, ps, {})


def test_mcp_shape_ignores_reelaborated_handshake_but_tracks_arithmetic():
    import subprocess

    design = Path(__file__).with_name("auto_multi_cycle_sweep_design.py").resolve()
    code = r"""
import sys
import PY_TO_LOGIC, AUTO_MULTI_CYCLE as mcp, pypeline
ps = PY_TO_LOGIC.PARSE_FILE(sys.argv[1])
group = next(iter(mcp.COLLECT_AUTO_MULTI_CYCLE_GROUPS(ps).values()))
original = mcp.MCP_SHAPE(group, ps)
pypeline.SET_AUTO_MULTI_CYCLE_LATENCY_CACHE({group.key: 6})
ps2 = PY_TO_LOGIC.PARSE_FILE(sys.argv[1])
group2 = next(iter(mcp.COLLECT_AUTO_MULTI_CYCLE_GROUPS(ps2).values()))
assert original == mcp.MCP_SHAPE(group2, ps2)
# A real data type change must invalidate the shape even with the same name.
ps2.FuncLogicLookupTable['mix'].wire_to_c_type['x'] = 'uint64_t'
assert original != mcp.MCP_SHAPE(group2, ps2)
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(design)],
        env=dict(os.environ, PYTHONPATH=str(Path(SWEEP.__file__).parent)),
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_mcp_provisional_confirm_down_once_restores_failed_trial():
    from unittest.mock import patch
    import AUTO_MULTI_CYCLE as mcp
    from scripted_sweep_backend import path

    logic = FakeLogic(
        "holder", wire_to_c_type={"launch": "uint32_t", "capture": "uint32_t"}
    )
    ps = FakeParserState({"a": logic})
    ps.main_mhz = {"a": 100}
    group = mcp.AutoMultiCycleGroup("a", SWEEP.C_TO_LOGIC.AutoMultiCycleConstraint("a"))
    group.paths = [("a", "launch", "capture")]
    shape = mcp.MCP_SHAPE(group, ps)
    params = SimpleNamespace(auto_multi_cycle_ncycles={"a": 6})
    passing = path("a", 4.0)
    passing.scope = "mcp:a:launch:capture"
    passing.requirement_ns = 60
    passing.slack_ns = 36
    passing.source_ns_per_clock = 10
    report = SimpleNamespace(path_reports={"clk": passing}, extra_paths=[passing])
    failed = path("a", 11.0)
    trial = SimpleNamespace(path_reports={"clk": failed}, extra_paths=[])
    with patch.object(
        mcp, "COLLECT_AUTO_MULTI_CYCLE_GROUPS", return_value={"a": group}
    ), patch.object(
        mcp, "AUTO_MULTI_CYCLE_GROUP_FOR_PATH_REPORT", return_value=group
    ), patch.object(
        mcp, "PROVISIONAL_MCP_SEEDS", {("a", shape): {"floor": 1, "seeded": 6}}
    ), patch.object(mcp, "CONFIRM_DOWN_USED", set()), patch.object(
        SWEEP.SYN,
        "SYN_TOOL",
        SimpleNamespace(SYN_AND_REPORT_TIMING_MULTIMAIN=lambda *a: trial),
    ), patch.object(SWEEP.SYN, "GET_TARGET_MHZ", return_value=100), patch.object(
        SWEEP, "GET_MAIN_INSTS_FOR_PATH_REPORT", return_value={"a"}
    ), patch.object(SWEEP, "RECORD_SYNTHESIS_OBSERVATION"):
        retained = SWEEP.CONFIRM_PROVISIONAL_MCP_SEEDS(report, ps, params)
        assert retained is report
        assert params.auto_multi_cycle_ncycles == {"a": 6}
        assert mcp.PROPOSE_CONFIRM_DOWN(report, ps, params) == {}
        # The budget is per shape, not per invocation or current count.
        params.auto_multi_cycle_ncycles["a"] = 7
        assert mcp.PROPOSE_CONFIRM_DOWN(report, ps, params) == {}


def test_optional_report_errors_do_not_block_the_log():
    import VIVADO

    ok = (
        "PYPELINEC_OPTIONAL_BEGIN\n"
        "ERROR: [Common 17-161] Invalid option value specified\n"
        "PYPELINEC_OPTIONAL_ERROR\tinvalid option\n"
        "PYPELINEC_OPTIONAL_END\n"
        "PYPELINEC_SYNTHESIS_COMPLETE\n"
    )
    VIVADO.REQUIRE_COMPLETE_LOG(ok, "optional.log")
    # An error outside the optional section still blocks reuse.
    try:
        VIVADO.REQUIRE_COMPLETE_LOG("ERROR: synth\n" + ok, "bad.log")
    except RuntimeError:
        pass
    else:
        raise AssertionError("accepted a required-step error")
    paths, coverage = VIVADO.PARSE_EXTRA_PATHS(ok)
    assert paths == [] and coverage["optional_error"]["error"] == "invalid option"
    # Non-positive requirement-minus-slack is not setup evidence.
    paths, _ = VIVADO.PARSE_EXTRA_PATHS(
        "PYPELINEC_PATH\tfailing\tclk\t12\t10\t1\t1\t10\ta/r[0]/C\tb/r[0]/D\tFDRE\tFDRE\n"
    )
    assert paths == []


def test_optional_tcl_is_caught_and_mcp_pairs_use_constraint_pins():
    import VIVADO, VHDL, AUTO_MULTI_CYCLE as mcp
    from unittest.mock import patch

    ps = FakeParserState({"main": FakeLogic("main")})
    ps.main_mhz = {"main": 40}
    params = SimpleNamespace(TimingParamsLookupTable={})
    with patch.object(VHDL, "GET_ENTITY_NAME", return_value="main_e"), patch.object(
        mcp,
        "GET_MCP_CELL_PATHS",
        return_value=[(("x", "launch", "capture"), "main_e/l_reg[*]", "main_e/c_reg[*]", None)],
    ):
        tcl = VIVADO.EXTRA_PATHS_TCL(params, ps)
    assert tcl.index("PYPELINEC_OPTIONAL_BEGIN") < tcl.index("catch") < tcl.index(
        "PYPELINEC_OPTIONAL_END"
    )
    assert "get_pins -quiet {main_e/l_reg[*]/C}" in tcl
    assert "get_pins -quiet {main_e/c_reg[*]/D}" in tcl
    assert "get_cells -quiet {main_e/l_reg[*]}" not in tcl
    assert tcl.count("{") == tcl.count("}")


def test_failing_evidence_sorts_first_and_planless_keeps_worst():
    from unittest.mock import patch
    import AUTO_MULTI_CYCLE as mcp
    from scripted_sweep_backend import path

    fast = path("fast", 6.0, period=5.0)  # 200 MHz goal: failing
    slow = path("slow", 8.0)  # 100 MHz goal: passing, larger delay
    report = SimpleNamespace(path_reports={}, extra_paths=[slow, fast])
    goals = {"fast": 200, "slow": 100}
    with patch.object(mcp, "COLLECT_AUTO_MULTI_CYCLE_GROUPS", return_value={}), patch.object(
        mcp, "AUTO_MULTI_CYCLE_GROUP_FOR_PATH_REPORT", return_value=None
    ), patch.object(SWEEP.SYN, "GET_TARGET_MHZ", side_effect=lambda m, p: goals[m]), patch.object(
        SWEEP, "GET_MAIN_INSTS_FOR_PATH_REPORT", side_effect=lambda p, *a: {p.start_reg_name.split("/")[0]}
    ):
        ordered = SWEEP.FEEDBACK_PATHS(report, None, None)
    assert [p.start_reg_name.split("/")[0] for p in ordered] == ["fast", "slow"]
    results = {}
    assert SWEEP._KEEP_WORST_PLANLESS(results, "m", 90.0, False, 100)
    assert not SWEEP._KEEP_WORST_PLANLESS(results, "m", 150.0, True, 100)
    assert results["m"] == (90.0, False, 100)


def _scripted_sweep_patches(backend, fresh, extra=()):
    import SYN

    noop = lambda *a, **k: None

    def landscape(root, *args):
        view = SWEEP.SliceLandscape(root, 20, 0.1)
        view.finalize({})
        return view

    return [
        (SYN, "SYN_TOOL", backend),
        (SYN, "GET_TARGET_MHZ", lambda m, p: 100),
        (SYN, "LOGIC_IS_ZERO_DELAY", lambda *a, **k: False),
        (SYN, "WRITE_REGISTERS_ESTIMATE_FILE", noop),
        (SYN, "WRITE_AREA_ESTIMATE_FILE", noop),
        (SYN, "ESTIMATE_DESIGN_AREA", lambda *a: {"total_area": 0}),
        (SYN, "PRINT_MEASURED_AREA_IF_AVAILABLE", noop),
        (SYN, "FUNC_SRC_LOC_STR", lambda *a: ""),
        (AUTO_PIPELINE, "GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP", fresh),
        (AUTO_PIPELINE, "COLLECT_AUTO_PIPELINE_REGIONS", lambda *a: []),
        (AUTO_PIPELINE, "CHECK_ADDED_LATENCY_CONTEXT", noop),
        (AUTO_PIPELINE, "WRITE_ALL_NON_ZERO_CLK_VHDL_FILES", noop),
        (AUTO_PIPELINE, "INVALIDATE_MODIFIED_INST_ANCESTOR_CACHES", lambda *a: set()),
        (AUTO_PIPELINE, "CHECK_AUTO_PIPELINE_CONSTRAINTS_REALIZED", noop),
        (SWEEP, "COLLECT_CUT_SUBTREES", lambda m, p: [m]),
        (SWEEP, "BUILD_SLICE_LANDSCAPE", landscape),
        (SWEEP, "PLAN_PIPELINE_PLACEMENTS", lambda *a, **k: ([], [])),
        (SWEEP, "RESOLVE_PIPELINABLE_HOTSPOT", lambda path, plan, ps: (None, None, "")),
        (SWEEP, "RUN_AS_WRITTEN_CHECKS", lambda *a: {}),
        (SWEEP, "GET_MAIN_INSTS_FOR_PATH_REPORT", lambda p, *a: {p.start_reg_name.split("/")[0]}),
        (SWEEP, "SUMMARIZE_SUBTREE_PIPELINE", lambda m, st, t, p: (False, [], len(t[m]._slices))),
        (SWEEP, "GET_SUBTREE_PIPELINE_STAGES", lambda plan, t, p: len(t[plan.main_inst]._slices)),
        (SWEEP, "WRITE_PIPELINE_PLACEMENT_TRACE", noop),
        (SWEEP, "WRITE_SWEEP_HISTORY", noop),
        (SWEEP, "LOAD_INTERNAL_PLACEMENT_CONFIG", lambda: None),
        (SWEEP, "PRINT_FLOOR_REPORT", noop),
        (SWEEP, "SWEEP_HISTORY", {}),
        (SWEEP, "SWEEP_OUTCOMES", {}),
        (SWEEP, "SYNTHESIS_OBSERVATIONS", []),
        (SWEEP, "CARRIED_LOCKS", {}),
        (SWEEP, "PIPELINE_MIN_EFFORT", 0),
    ] + list(extra)


def test_passing_optional_path_never_erases_a_capped_mcp_failure():
    from unittest.mock import patch
    from contextlib import ExitStack
    from scripted_sweep_backend import ScriptedBackend, path
    import SYN, AUTO_MULTI_CYCLE as mcp

    order = ["a", "b"]
    ps = FakeParserState({m: FakeLogic(m) for m in order})
    ps.main_mhz = {m: 100 for m in order}
    ps.FuncToInstances = {m: {m} for m in order}
    for logic in ps.LogicInstLookupTable.values():
        logic.delay = 5
        logic.delay_is_estimated = False

    def fresh(_):
        return {m: AUTO_PIPELINE.TimingParams(m, ps.LogicInstLookupTable[m]) for m in order}

    group = mcp.AutoMultiCycleGroup("g", SWEEP.C_TO_LOGIC.AutoMultiCycleConstraint("g"))
    group.constraint.max_latency = 1  # capped: the failure cannot be repaired
    params = SimpleNamespace(TimingParamsLookupTable=fresh(ps), auto_multi_cycle_ncycles={"g": 1})

    def rule(ps, params):
        return [path("a", 30.0, pair="mcp"), path("a", 5.0), path("b", 5.0)]

    backend = ScriptedBackend(rule, multiple=True)
    with tempfile.TemporaryDirectory() as out, ExitStack() as stack:
        extra = [
            (SYN, "SYN_OUTPUT_DIRECTORY", out),
            (mcp, "COLLECT_AUTO_MULTI_CYCLE_GROUPS", lambda p: {"g": group}),
            (mcp, "SEED_COUNTS", lambda *a: None),
            (mcp, "PROPOSE_CONFIRM_DOWN", lambda *a: {}),
            (
                mcp,
                "AUTO_MULTI_CYCLE_GROUP_FOR_PATH_REPORT",
                lambda p, *a: group if "/mcp/" in p.start_reg_name else None,
            ),
        ]
        for obj, key, value in _scripted_sweep_patches(backend, fresh, extra):
            stack.enter_context(patch.object(obj, key, value))
        result = SWEEP.DO_PLANNED_THROUGHPUT_SWEEP(ps, params)
    failing = {f[0]: f[3] for f in result.sweep_timing_failures}
    assert "a" in failing and failing["a"].startswith("auto_multi_cycle_latency_limit"), failing
    assert "b" not in failing, failing


def test_carried_locks_belong_to_their_main_and_obey_lock_rules():
    from unittest.mock import patch

    m = SWEEP.C_TO_LOGIC.SUBMODULE_MARKER
    helper = FakeLogic("helper")
    enc, dec = FakeLogic("enc"), FakeLogic("dec")
    enc.submodule_instances = dec.submodule_instances = {"h": "helper"}
    ps = FakeParserState({"enc": enc, "dec": dec, "enc" + m + "h": helper, "dec" + m + "h": helper})
    ps.FuncToInstances = {"helper": {"enc" + m + "h", "dec" + m + "h"}}
    helper.delay, helper.delay_is_estimated = 5, False
    zero = lambda: {i: AUTO_PIPELINE.TimingParams(i, l) for i, l in ps.LogicInstLookupTable.items()}
    built = zero()
    built["dec" + m + "h"].SET_SLICES([0.5])
    inst = "dec" + m + "h"
    lock = SWEEP.MiniSweepLock(
        [0.5],
        concrete=AUTO_PIPELINE.CAPTURE_CONCRETE_PIPELINE(inst, built, ps),
        model_fingerprint=SWEEP.SUBTREE_MODEL_FINGERPRINT(inst, ps),
    )
    with patch.object(SWEEP, "CARRIED_LOCKS", {}), patch.object(
        AUTO_PIPELINE, "ADDED_LATENCY_BLOCKER", return_value=None
    ), patch.object(
        AUTO_PIPELINE, "FUNC_HAS_HIER_ALLOWING_ADDED_LATENCY_TO_RAW_VHDL", return_value=True
    ), patch.object(SWEEP, "SET_MINISWEEP_BOUNDARY_STRATEGY"):
        owner = SWEEP.MainSweepPlan("dec", 40)
        owner.locked[inst] = lock
        SWEEP.STORE_CARRIED_LOCKS({"dec": owner}, ps)
        assert len(SWEEP.CARRIED_LOCKS) == 1
        # Independent MAIN depths: another MAIN's instances never inherit it.
        other = SWEEP.MainSweepPlan("enc", 40)
        SWEEP.LOAD_CARRIED_LOCKS(other, ps, zero())
        assert other.locked == {}
        again = SWEEP.MainSweepPlan("dec", 40)
        SWEEP.LOAD_CARRIED_LOCKS(again, ps, zero())
        assert set(again.locked) == {inst}
        # Same rules as the mini-sweep: never inside a constrained region.
        region = SWEEP.MainSweepPlan("dec", 40)
        region.regions = [SimpleNamespace(inst=inst)]
        SWEEP.LOAD_CARRIED_LOCKS(region, ps, zero())
        assert region.locked == {}
        # A preserved MAIN keeps the lock only if its snapshot built it.
        kept = SWEEP.MainSweepPlan("dec", 40)
        SWEEP.LOAD_CARRIED_LOCKS(kept, ps, zero(), AUTO_PIPELINE.CAPTURE_CONCRETE_PIPELINE("dec", zero(), ps))
        assert kept.locked == {}
        SWEEP.LOAD_CARRIED_LOCKS(kept, ps, zero(), AUTO_PIPELINE.CAPTURE_CONCRETE_PIPELINE("dec", built, ps))
        assert set(kept.locked) == {inst}
        # A retained implementation without the lock prunes the stale entry.
        SWEEP.STORE_CARRIED_LOCKS({"dec": SWEEP.MainSweepPlan("dec", 40)}, ps)
        assert SWEEP.CARRIED_LOCKS == {}


def test_locked_interior_match_uses_marker_prefix_and_hotspot():
    from unittest.mock import patch
    import VHDL

    marker = SWEEP.C_TO_LOGIC.SUBMODULE_MARKER
    ps = FakeParserState({"main": FakeLogic("main"), "main" + marker + "_hot_": FakeLogic("hot")})
    plan = SWEEP.MainSweepPlan("main", 80)
    plan.locked["main" + marker + "_hot_"] = SWEEP.MiniSweepLock([0.5])
    local = VHDL.WIRE_TO_VHDL_NAME("_hot_", ps)
    path = SimpleNamespace(
        start_reg_name=f"main_entity/{local}/mul/register_a[0]",
        end_reg_name=f"main_entity/{local}/mul/register_b[0]",
    )
    with patch.object(VHDL, "GET_ENTITY_NAME", return_value="main_entity"):
        assert SWEEP.PATH_INSIDE_LOCK(path, plan, ps, {})
        assert SWEEP.PATH_INSIDE_LOCK(path, plan, ps, {}, "hot")
        assert not SWEEP.PATH_INSIDE_LOCK(path, plan, ps, {}, "other")


def test_mcp_confirmation_repair_is_bounded():
    from unittest.mock import patch
    from contextlib import ExitStack
    from scripted_sweep_backend import ScriptedBackend, path
    import SYN, VHDL, AUTO_MULTI_CYCLE as mcp

    ps = FakeParserState({"a": FakeLogic("a")})
    ps.main_mhz = {"a": 100}
    ps.part = "scripted"
    table = {"a": AUTO_PIPELINE.TimingParams("a", ps.LogicInstLookupTable["a"])}
    params = SimpleNamespace(TimingParamsLookupTable=table, auto_multi_cycle_ncycles={"a": 1})
    groups = {"a": mcp.AutoMultiCycleGroup("a", SWEEP.C_TO_LOGIC.AutoMultiCycleConstraint("a"))}

    def rule(ps, params):
        n = params.auto_multi_cycle_ncycles["a"]
        row = path("a", 30.0)  # grows with the count: never repairable
        row.requirement_ns, row.slack_ns = n * 10, n * 10 - 30.0 * n
        return [row]

    backend = ScriptedBackend(rule, True)
    noop = lambda *a, **kw: None
    with ExitStack() as stack:
        for obj, name, value in [
            (SYN, "SYN_TOOL", backend),
            (SYN, "PART_SET_TOOL", noop),
            (SYN, "GET_TARGET_MHZ", lambda m, p: 100),
            (SYN, "LOGIC_IS_ZERO_DELAY", lambda *a, **kw: False),
            (SYN, "WRITE_BLACK_BOX_FILES", noop),
            (SYN, "WRITE_REGISTERS_ESTIMATE_FILE", noop),
            (SYN, "WRITE_AREA_ESTIMATE_FILE", noop),
            (SYN, "ESTIMATE_DESIGN_AREA", lambda *a: {"total_area": 0}),
            (SYN, "PRINT_MEASURED_AREA_IF_AVAILABLE", noop),
            (VHDL, "WRITE_CLK_CROSS_ENTITIES", noop),
            (VHDL, "WRITE_MULTIMAIN_TOP", noop),
            (AUTO_PIPELINE, "INVALIDATE_MODIFIED_INST_ANCESTOR_CACHES", lambda *a: set()),
            (AUTO_PIPELINE, "WRITE_ALL_NON_ZERO_CLK_VHDL_FILES", noop),
            (SWEEP, "COLLECT_CUT_SUBTREES", lambda *a: []),
            (SWEEP, "RECORD_CONFIRMATION_RESULTS", noop),
            (SWEEP, "SYNTHESIS_OBSERVATIONS", []),
            (SWEEP, "GET_MAIN_INSTS_FOR_PATH_REPORT", lambda p, *a: {"a"}),
            (mcp, "COLLECT_AUTO_MULTI_CYCLE_GROUPS", lambda p: groups),
            (mcp, "SEED_COUNTS", noop),
            (mcp, "PROPOSE_CONFIRM_DOWN", lambda *a: {}),
            (mcp, "AUTO_MULTI_CYCLE_GROUP_FOR_PATH_REPORT", lambda p, *a: groups["a"]),
        ]:
            stack.enter_context(patch.object(obj, name, value))
        _result, met = SWEEP.DO_SEEDED_CONFIRM_OR_SWEEP(ps, params)
    assert not met
    assert len(backend.calls) == SWEEP.MAX_CONFIRMATION_MCP_REPAIRS + 1


def test_confirm_down_reuses_an_observed_candidate():
    from unittest.mock import patch
    import AUTO_MULTI_CYCLE as mcp
    from scripted_sweep_backend import path

    trial = SimpleNamespace(path_reports={"clk": path("a", 11.0)}, extra_paths=[])
    report = SimpleNamespace(path_reports={"clk": path("a", 4.0)}, extra_paths=[])
    params = SimpleNamespace(auto_multi_cycle_ncycles={"a": 6})
    seen = {"candidate": trial}
    with patch.object(mcp, "PROPOSE_CONFIRM_DOWN", return_value={"a": 3}), patch.object(
        SWEEP, "IMPLEMENTATION_SIGNATURE", return_value="candidate"
    ), patch.object(
        SWEEP.SYN,
        "SYN_TOOL",
        SimpleNamespace(
            SYN_AND_REPORT_TIMING_MULTIMAIN=lambda *a: (_ for _ in ()).throw(
                AssertionError("re-synthesized an observed candidate")
            )
        ),
    ), patch.object(SWEEP.SYN, "GET_TARGET_MHZ", return_value=100), patch.object(
        SWEEP, "GET_MAIN_INSTS_FOR_PATH_REPORT", return_value={"a"}
    ):
        assert SWEEP.CONFIRM_PROVISIONAL_MCP_SEEDS(report, None, params, seen) is report
    assert params.auto_multi_cycle_ncycles == {"a": 6}


def test_isolated_mcp_evidence_keeps_the_worst_replica():
    from unittest.mock import patch
    import VHDL, AUTO_MULTI_CYCLE as mcp
    from scripted_sweep_backend import path

    group = mcp.AutoMultiCycleGroup("g", SWEEP.C_TO_LOGIC.AutoMultiCycleConstraint("g"))
    group.paths = [("top", "launch", "capture")]
    ps = FakeParserState({"top": FakeLogic("top")})

    def report(raw):
        row = path("top", raw / 2, pair="x")
        row.start_reg_name, row.end_reg_name = "top/x/launch_reg[0]", "top/x/capture_reg[0]"
        row.requirement_ns, row.slack_ns, row.end_pin_name = 20.0, 20.0 - raw, "D"
        return SimpleNamespace(path_reports={"clk": row}, extra_paths=[])

    evidence = {}
    with patch.object(mcp, "COLLECT_AUTO_MULTI_CYCLE_GROUPS", return_value={"g": group}), patch.object(
        VHDL, "GET_ENTITY_NAME", return_value="top"
    ), patch.object(
        mcp, "GET_MCP_CELL_PATHS", return_value=[(("x", "launch", "capture"), "top/x/launch_reg[*]", "top/x/capture_reg[*]", group.constraint)]
    ), patch.object(mcp, "MCP_EFFECTIVE_NCYCLES", return_value=2), patch.object(
        mcp, "MCP_SHAPE", return_value="shape"
    ), patch.object(mcp, "ISOLATED_MCP_EVIDENCE", evidence):
        group.constraint.key = "g"
        mcp.REMEMBER_ISOLATED_REPORTS(report(57.0), ps, SimpleNamespace(TimingParamsLookupTable={}), "top")
        mcp.REMEMBER_ISOLATED_REPORTS(report(45.0), ps, SimpleNamespace(TimingParamsLookupTable={}), "top")
    assert evidence == {("g", "shape"): 57.0}


def test_lock_survives_real_reelaboration_with_resized_lanes():
    """A real two-pass parse (like pin-and-confirm): pass 2 resizes the
    latency-sized lanes and adds helper instances. The owning MAIN reuses the
    concrete interior on every instance; the other MAIN inherits nothing."""
    import subprocess

    design = Path(__file__).with_name("c_structs_pkg_relayout_design.py").resolve()
    code = r"""
import sys, copy, tempfile
import C_TO_LOGIC, PY_TO_LOGIC, SYN, AUTO_PIPELINE, SWEEP, pypeline
SYN.SYN_OUTPUT_DIRECTORY = tempfile.mkdtemp()
m = C_TO_LOGIC.SUBMODULE_MARKER
enc, dec = "c_structs_pkg_relayout_encrypt", "c_structs_pkg_relayout_decrypt"
def parse(cache):
    pypeline.SET_AUTO_PIPELINE_LATENCY_CACHE(cache)
    return PY_TO_LOGIC.PARSE_FILE(sys.argv[1])
ps1 = parse({})
func = [f for f in ps1.FuncToInstances if f.startswith("body_v_direction_encrypt")][0]
table1 = AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(ps1)
plan1 = SWEEP.MainSweepPlan(enc, 100)
targets, _ = SWEEP.MINISWEEP_LOCK_TARGETS(func, plan1, ps1)
assert len(targets) == 2 and SWEEP.LOCK_BLOCKED_REASON(func, plan1, targets, ps1) is None
isolated = copy.deepcopy(table1)
leaf = [i for i in isolated if i.startswith(targets[0] + m) and "MULT" in i][0]
isolated[leaf].SET_SLICES([0.5])
concrete = AUTO_PIPELINE.CAPTURE_CONCRETE_PIPELINE(targets[0], isolated, ps1)
for inst in targets:
    plan1.locked[inst] = SWEEP.MiniSweepLock(
        [0.5], concrete=concrete,
        model_fingerprint=SWEEP.SUBTREE_MODEL_FINGERPRINT(inst, ps1))
SWEEP.STORE_CARRIED_LOCKS({enc: plan1}, ps1)
keys = {k for l in ps1.FuncLogicLookupTable.values()
        for k in l.sub_inst_to_auto_pipeline_key.values()}
ps2 = parse({k: 3 for k in keys})  # lanes 2 -> 5 in both directions
table2 = AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(ps2)
plan2 = SWEEP.MainSweepPlan(enc, 100)
SWEEP.LOAD_CARRIED_LOCKS(plan2, ps2, table2)
new_targets, _ = SWEEP.MINISWEEP_LOCK_TARGETS(func, plan2, ps2)
assert len(new_targets) == 5 and sorted(plan2.locked) == sorted(new_targets)
table2 = SWEEP.APPLY_LOCKS(plan2, ps2, table2)
strip = lambda c: {r: {k: v for k, v in rec.items() if k != "fixed"} for r, rec in c.items()}
for inst in new_targets:
    assert strip(AUTO_PIPELINE.CAPTURE_CONCRETE_PIPELINE(inst, table2, ps2)) == strip(concrete), inst
other = SWEEP.MainSweepPlan(dec, 100)
SWEEP.LOAD_CARRIED_LOCKS(other, ps2, table2)
assert other.locked == {}
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(design)],
        env=dict(os.environ, PYTHONPATH=str(Path(SWEEP.__file__).parent)),
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-3000:]


def test_seed_replays_entity_hash_after_real_reelaboration():
    """A resized lane wrapper and renamed call sites preserve heterogeneous
    placements in repeated helpers, including the deliberately empty calls."""
    import subprocess
    source = Path(__file__).with_name("c_structs_pkg_relayout_design.py").read_text()
    source = source.replace("def make_mac(direction: str):", "@hw_func\ndef seed_step(x: uint32_t) -> uint32_t:\n    return x * x\n\n\ndef make_mac(direction: str):")
    source = source.replace("return x * x + salt", "return seed_step(seed_step(x)) + salt")
    code = r"""
import sys, tempfile
from pathlib import Path
import PY_TO_LOGIC, SYN, AUTO_PIPELINE, pypeline, C_TO_LOGIC
SYN.SYN_OUTPUT_DIRECTORY = tempfile.mkdtemp()
file = Path(sys.argv[1])
pypeline.SET_AUTO_PIPELINE_LATENCY_CACHE({})
a = PY_TO_LOGIC.PARSE_FILE(str(file))
ta = AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(a)
m = C_TO_LOGIC.SUBMODULE_MARKER
roots = [i + m + local for i,logic in a.LogicInstLookupTable.items()
         for local in logic.sub_inst_to_auto_pipeline_key]
for root in roots:
    leaves = sorted(i for i in ta if i.startswith(root + m)
                    and a.LogicInstLookupTable[i].func_name == "seed_step")
    assert len(leaves) == 2, leaves
    ta[leaves[0]].SET_HAS_OUT_REGS(True)
    # One exact bit split in the final add must also survive.
    adds = [i for i in ta if i.startswith(root + m)
            and a.LogicInstLookupTable[i].func_name.startswith("BIN_OP_PLUS")]
    assert len(adds) == 1, adds
    ta[adds[0]].SET_EXACT_BIT_BOUNDARIES((9,), 32)
    ta[adds[0]].params_are_fixed = True
latencies, divergent = AUTO_PIPELINE.HARVEST_AUTO_PIPELINE_LATENCIES(a, ta)
assert not divergent
saved = {a.LogicInstLookupTable[root].func_name: (AUTO_PIPELINE.CAPTURE_CONCRETE_PIPELINE(root,ta,a),ta[root].GET_HASH_EXT(ta,a),ta[root].GET_TOTAL_LATENCY(a,ta)) for root in roots}
# Move only the caller source locations; function/type identity is unchanged.
file.write_text(file.read_text().replace("@MAIN\ndef", "\n\n@MAIN\ndef"))
pypeline.SET_AUTO_PIPELINE_LATENCY_CACHE(latencies)
b = PY_TO_LOGIC.PARSE_FILE(str(file))
tb = AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(b)
tb, missing = AUTO_PIPELINE.SEED_TIMING_PARAMS_FROM_PREVIOUS(a,ta,b,tb)
assert not missing
new_roots = [i + m + local for i,logic in b.LogicInstLookupTable.items()
             for local in logic.sub_inst_to_auto_pipeline_key]
assert set(roots).isdisjoint(new_roots), (roots,new_roots)
assert len(new_roots) > len(roots), (roots,new_roots)
for root in new_roots:
    concrete, entity_hash, depth = saved[b.LogicInstLookupTable[root].func_name]
    assert AUTO_PIPELINE.CAPTURE_CONCRETE_PIPELINE(root,tb,b) == concrete
    assert tb[root].GET_HASH_EXT(tb,b) == entity_hash
    assert tb[root].GET_TOTAL_LATENCY(b,tb) == depth
print("Exact region parameters, entity hashes and depths preserved after resized/renamed re-elaboration")
"""
    with tempfile.TemporaryDirectory() as directory:
        design = Path(directory) / "seed_replay_design.py"
        design.write_text(source)
        result = subprocess.run([sys.executable, "-c", code, str(design)],
            env=dict(os.environ, PYTHONPATH=str(Path(SWEEP.__file__).parent)),
            text=True, capture_output=True)
        assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-4000:]


def test_confirmation_prints_one_worst_value_per_main():
    import io
    from contextlib import redirect_stdout
    from unittest.mock import patch
    from scripted_sweep_backend import path
    import SYN
    ps = SimpleNamespace(LogicInstLookupTable={"m": FakeLogic("m")})
    rows = [path("m", 12.0), path("m", 11.0), path("m", 13.0)]
    with patch.object(SWEEP, "FEEDBACK_PATHS", return_value=rows), patch.object(
        SWEEP, "GET_MAIN_INSTS_FOR_PATH_REPORT", return_value={"m"}
    ), patch.object(SYN, "GET_TARGET_MHZ", return_value=80), redirect_stdout(io.StringIO()) as captured:
        met, measured, failures = SWEEP.REPORT_CONFIRMATION_RESULTS(None, ps, None)
    assert not met and measured == {"m": 1000.0 / 13.0}
    assert len(failures) == 1
    lines = captured.getvalue().splitlines()
    assert len(lines) == 1 and lines[0].startswith("FAIL m: 76.92 MHz")
    assert "worst reported path" in lines[0]


def test_estimated_unsliceable_span_is_not_an_impossibility_verdict():
    import io
    from contextlib import redirect_stdout
    blame = SimpleNamespace(inst_path="main____mux", reason="inside_state_regs_container", hard=True)
    landscape = SimpleNamespace(total_units=2361, units_to_ns=0.1,
        floor_mhz=lambda: 46.5, floor_blame=blame, floor_ns=21.5)
    plan = SimpleNamespace(main_inst="main", subtrees=["main"], landscapes={"main":landscape},
        target_period_ns=12.5, target_mhz=80)
    ps = SimpleNamespace(LogicInstLookupTable={"main":FakeLogic("main")})
    with redirect_stdout(io.StringIO()) as captured:
        SWEEP.PRINT_FLOOR_REPORT(plan, ps)
    text = captured.getvalue()
    assert "estimated frequency ceiling" in text and "not a timing verdict" in text
    assert "cannot be met" not in text and "predicted floor" not in text


def test_pipelined_confirmation_failure_preserves_unaffected_mains():
    from unittest.mock import patch
    from contextlib import ExitStack
    from scripted_sweep_backend import ScriptedBackend, path
    import SYN, VHDL, AUTO_MULTI_CYCLE as mcp

    ps = FakeParserState({m: FakeLogic(m) for m in ("a", "b")})
    ps.main_mhz = {"a": 100, "b": 100}
    ps.part = "scripted"
    table = {m: AUTO_PIPELINE.TimingParams(m, l) for m, l in ps.LogicInstLookupTable.items()}
    table["b"].SET_SLICES([0.5])
    params = SimpleNamespace(TimingParamsLookupTable=table, auto_multi_cycle_ncycles={})
    seen = {}

    def fallback(ps_, params_):
        seen.update(params_.confirmation_preserved_mains)
        return params_

    backend = ScriptedBackend(lambda ps, p: [path("a", 15.0), path("b", 5.0)], True)
    noop = lambda *a, **kw: None
    with ExitStack() as stack:
        for obj, name, value in [
            (SYN, "SYN_TOOL", backend),
            (SYN, "PART_SET_TOOL", noop),
            (SYN, "GET_TARGET_MHZ", lambda m, p: 100),
            (SYN, "LOGIC_IS_ZERO_DELAY", lambda *a, **kw: False),
            (SYN, "WRITE_BLACK_BOX_FILES", noop),
            (SYN, "WRITE_REGISTERS_ESTIMATE_FILE", noop),
            (SYN, "WRITE_AREA_ESTIMATE_FILE", noop),
            (SYN, "ESTIMATE_DESIGN_AREA", lambda *a: {"total_area": 0}),
            (SYN, "PRINT_MEASURED_AREA_IF_AVAILABLE", noop),
            (VHDL, "WRITE_CLK_CROSS_ENTITIES", noop),
            (VHDL, "WRITE_MULTIMAIN_TOP", noop),
            (AUTO_PIPELINE, "INVALIDATE_MODIFIED_INST_ANCESTOR_CACHES", lambda *a: set()),
            (AUTO_PIPELINE, "WRITE_ALL_NON_ZERO_CLK_VHDL_FILES", noop),
            # Both MAINs are pipelined (a fallback sweep can replan them)
            (SWEEP, "COLLECT_CUT_SUBTREES", lambda m, p: [m]),
            (SWEEP, "SUMMARIZE_SUBTREE_PIPELINE", lambda *a: (False, [], 0)),
            (SWEEP, "RECORD_CONFIRMATION_RESULTS", noop),
            (SWEEP, "SYNTHESIS_OBSERVATIONS", []),
            (SWEEP, "GET_MAIN_INSTS_FOR_PATH_REPORT", lambda p, *a: {p.start_reg_name.split("/")[0]}),
            (SWEEP, "DO_PLANNED_THROUGHPUT_SWEEP", fallback),
            (mcp, "COLLECT_AUTO_MULTI_CYCLE_GROUPS", lambda p: {}),
            (mcp, "SEED_COUNTS", noop),
            (mcp, "PROPOSE_CONFIRM_DOWN", lambda *a: {}),
            (mcp, "AUTO_MULTI_CYCLE_GROUP_FOR_PATH_REPORT", lambda *a: None),
        ]:
            stack.enter_context(patch.object(obj, name, value))
        _result, met = SWEEP.DO_SEEDED_CONFIRM_OR_SWEEP(ps, params)
    assert not met and len(backend.calls) == 1
    # Only the failing MAIN is replanned; the passing one keeps what was built.
    assert set(seen) == {"b"} and seen["b"][""]["slices"] == [0.5]


def test_confirmation_skipped_when_mcp_seed_changes_consumed_count():
    """A consumed AUTO_MULTI_CYCLE count sets the handshake's compare
    constant, so a changed seed means re-elaboration is certain. Only a
    count that matches the consumed hardware is worth a confirmation."""
    from unittest.mock import patch
    from contextlib import ExitStack
    from scripted_sweep_backend import ScriptedBackend, path
    import SYN, VHDL, AUTO_MULTI_CYCLE as mcp

    def run(seeded):
        ps = FakeParserState({"a": FakeLogic("a")})
        ps.main_mhz = {"a": 100}
        ps.part = "scripted"
        table = {"a": AUTO_PIPELINE.TimingParams("a", ps.LogicInstLookupTable["a"])}
        params = SimpleNamespace(TimingParamsLookupTable=table, auto_multi_cycle_ncycles={})
        backend = ScriptedBackend(lambda ps, p: [path("a", 5.0)], True)
        noop = lambda *a, **kw: None
        with ExitStack() as stack:
            for obj, name, value in [
                (SYN, "SYN_TOOL", backend),
                (SYN, "PART_SET_TOOL", noop),
                (SYN, "GET_TARGET_MHZ", lambda m, p: 100),
                (SYN, "LOGIC_IS_ZERO_DELAY", lambda *a, **kw: False),
                (SYN, "WRITE_BLACK_BOX_FILES", noop),
                (SYN, "WRITE_REGISTERS_ESTIMATE_FILE", noop),
                (SYN, "WRITE_AREA_ESTIMATE_FILE", noop),
                (SYN, "ESTIMATE_DESIGN_AREA", lambda *a: {"total_area": 0}),
                (SYN, "PRINT_MEASURED_AREA_IF_AVAILABLE", noop),
                (VHDL, "WRITE_CLK_CROSS_ENTITIES", noop),
                (VHDL, "WRITE_MULTIMAIN_TOP", noop),
                (AUTO_PIPELINE, "INVALIDATE_MODIFIED_INST_ANCESTOR_CACHES", lambda *a: set()),
                (AUTO_PIPELINE, "WRITE_ALL_NON_ZERO_CLK_VHDL_FILES", noop),
                (SWEEP, "COLLECT_CUT_SUBTREES", lambda *a: []),
                (SWEEP, "RECORD_CONFIRMATION_RESULTS", noop),
                (SWEEP, "SYNTHESIS_OBSERVATIONS", []),
                (SWEEP, "GET_MAIN_INSTS_FOR_PATH_REPORT", lambda p, *a: {"a"}),
                (mcp, "COLLECT_AUTO_MULTI_CYCLE_GROUPS", lambda p: {}),
                (mcp, "SEED_COUNTS", lambda ps_, params_: dict(seeded)),
                (mcp, "ELABORATED_AUTO_MULTI_CYCLE_NCYCLES", lambda p: {"k": 3}),
                (mcp, "PROPOSE_CONFIRM_DOWN", lambda *a: {}),
                (mcp, "AUTO_MULTI_CYCLE_GROUP_FOR_PATH_REPORT", lambda *a: None),
            ]:
                stack.enter_context(patch.object(obj, name, value))
            _result, met = SWEEP.DO_SEEDED_CONFIRM_OR_SWEEP(ps, params)
        return met, len(backend.calls)

    assert run({"k": 7}) == (None, 0)
    assert run({"k": 3}) == (True, 1)


def _run_trim_sweep(stage_delays_by_cuts, effort=2, uncut_delay=None):
    """Script stage delays independently of cut count, with a second uncut
    subtree in the same MAIN. Use real path attribution over both landscapes.
    Only the planner/lowering and backend are replaced; trimming, retention,
    implementation identity and the synthesis budget use the real sweep loop.
    """
    from unittest.mock import patch
    from contextlib import ExitStack
    from scripted_sweep_backend import ScriptedBackend, path
    import SYN

    marker = SWEEP.C_TO_LOGIC.SUBMODULE_MARKER
    pipe, side = "a" + marker + "pipe", "a" + marker + "side"
    main, pipe_logic, side_logic = FakeLogic("a"), FakeLogic("pipe_root"), FakeLogic("side_root")
    main.submodule_instances = {"pipe": "pipe_root", "side": "side_root"}
    ps = FakeParserState({"a": main, pipe: pipe_logic, side: side_logic})
    ps.main_mhz = {"a": 100}
    ps.FuncToInstances = {l.func_name: {i} for i, l in ps.LogicInstLookupTable.items()}
    for logic in ps.FuncLogicLookupTable.values():
        logic.delay, logic.delay_is_estimated = 40, False

    def fresh(_):
        return {i: AUTO_PIPELINE.TimingParams(i, l) for i, l in ps.LogicInstLookupTable.items()}

    def landscape(root, *args):
        view = SWEEP.SliceLandscape(root, 20, 0.1)
        func = "pipe_op" if root == pipe else "side_op"
        segment = SWEEP.Segment(root + marker + "op", func, 0, 20, SWEEP.Segment.SLICEABLE)
        segment.ancestor_funcs = {ps.LogicInstLookupTable[root].func_name, func}
        view.segments.append(segment)
        view.finalize({})
        return view

    def placements(view, budget, fixed_placements=()):
        if view.subtree_root_inst == side:
            return [], []
        # Give the real loop distinct candidates at successively lower budgets.
        n = max(1, min(4, round(4 * view.budget_units_for_period(10.0) / budget)))
        cuts = [round(20 * (i + 1) / (n + 1)) for i in range(n)]
        return cuts, [SimpleNamespace(axis_unit=c, to_dict=lambda c=c: {"axis_unit": c}) for c in cuts]

    def apply(placed, ps_, tpl, **kw):
        tpl[pipe].SET_SLICES([(i + 1) / (len(placed) + 1.0) for i in range(len(placed))])
        return tpl

    observed_cuts = []

    def rule(ps_, params_):
        table = params_.TimingParamsLookupTable
        n = len(table[pipe]._slices)
        assert table[side].IS_EMPTY(), table[side]._slices
        observed_cuts.append(n)
        reports = [path("a", max(stage_delays_by_cuts[n]), pair="pipe/pipe_op")]
        if uncut_delay is not None:
            reports.append(path("a", uncut_delay, pair="side/side_op"))
        return reports

    backend = ScriptedBackend(rule)
    params = SimpleNamespace(TimingParamsLookupTable=fresh(ps), auto_multi_cycle_ncycles={})
    with tempfile.TemporaryDirectory() as out, ExitStack() as stack:
        extra = [
            (SYN, "SYN_OUTPUT_DIRECTORY", out),
            (SWEEP, "PIPELINE_MIN_EFFORT", effort),
            (SWEEP, "COLLECT_CUT_SUBTREES", lambda *a: [pipe, side]),
            (SWEEP, "BUILD_SLICE_LANDSCAPE", landscape),
            (SWEEP, "PLAN_PIPELINE_PLACEMENTS", placements),
            (SWEEP, "CHUNK_SELECTED_MUX_OUTPUT_BANKS", lambda placed, *a: placed),
            (SWEEP, "APPLY_PIPELINE_PLACEMENTS", apply),
            (SWEEP, "CHECK_PIPELINE_PLACEMENTS_REALIZED", lambda *a: None),
            (SWEEP, "DROP_NON_DEEPENING_PLACEMENTS", lambda root, cuts, placed, *a: (cuts, placed)),
            (SWEEP, "PIPELINE_PLACEMENT_FINGERPRINT", lambda placed, locked: repr(sorted((k, len(v)) for k, v in placed.items()))),
            (SWEEP, "SUMMARIZE_SUBTREE_PIPELINE", lambda m, st, t, p: (False, [], len(t[pipe]._slices))),
            (SWEEP, "GET_SUBTREE_PIPELINE_STAGES", lambda plan, t, p: len(t[pipe]._slices)),
            (AUTO_PIPELINE, "ADDED_LATENCY_BLOCKER", lambda *a: None),
            (AUTO_PIPELINE.TimingParams, "GET_TOTAL_LATENCY", lambda self, ps_, t: sum(
                len(t[i]._slices) for i in t if i == self.inst_name or i.startswith(self.inst_name + marker))),
        ]
        for obj, key, value in _scripted_sweep_patches(backend, fresh, extra):
            stack.enter_context(patch.object(obj, key, value))
        result = SWEEP.DO_PLANNED_THROUGHPUT_SWEEP(ps, params)
        signature = SWEEP.IMPLEMENTATION_SIGNATURE(ps, result)
    assert not result.sweep_timing_failures, result.sweep_timing_failures
    retained_cuts = len(result.TimingParamsLookupTable[pipe]._slices)
    # Restoration must use the actual passing implementation, not just its count.
    assert signature == backend.calls[observed_cuts.index(retained_cuts)]
    return observed_cuts, retained_cuts


def test_trim_probes_uneven_stages_despite_small_timing_margin():
    # Merging two 2 ns stages leaves the 9.95 ns bottleneck unchanged.
    # A cut-count ratio incorrectly predicted an 80.4 MHz ceiling for 3 cuts.
    stages = {4: [9.95, 2, 2, 2, 2], 3: [9.95, 4, 2, 2], 2: [11.95, 4, 2]}
    assert _run_trim_sweep(stages) == ([4, 3, 2], 3)


def test_trim_probes_when_worst_path_is_in_an_uncut_subtree():
    # The side path sets 100.5 MHz throughout. Removing pipe registers cannot
    # scale that path's delay. Both probes pass; stop at the two-probe budget.
    stages = {4: [2, 2, 2, 2, 2], 3: [4, 2, 2, 2], 2: [4, 4, 2]}
    assert _run_trim_sweep(stages, uncut_delay=9.95) == ([4, 3, 2], 2)


def test_trim_failed_probe_restores_passing_implementation():
    stages = {4: [9.95, 2, 2, 2, 2], 3: [11.95, 2, 2, 2]}
    assert _run_trim_sweep(stages) == ([4, 3], 4)


def test_trim_zero_effort_accepts_first_passing_implementation():
    assert _run_trim_sweep({4: [9.95, 2, 2, 2, 2]}, effort=0) == ([4], 4)


def test_replayed_plan_keeps_the_landscape_its_cuts_came_from():
    """A met MAIN replays its snapshot while a delay-model refresh shrinks the
    landscape (the measured fallback). Its cut offsets must not be evaluated
    against the rebuilt axis (the 40 MHz WireGuard run's IndexError)."""
    from unittest.mock import patch
    from contextlib import ExitStack
    from scripted_sweep_backend import ScriptedBackend, path
    import SYN

    order = ["a", "b"]
    ps = FakeParserState({m: FakeLogic(m) for m in order})
    ps.main_mhz = {m: 100 for m in order}
    ps.FuncToInstances = {m: {m} for m in order}
    for logic in ps.LogicInstLookupTable.values():
        logic.delay, logic.delay_is_estimated = 5, False

    def fresh(_):
        return {m: AUTO_PIPELINE.TimingParams(m, ps.LogicInstLookupTable[m]) for m in order}

    built = {}

    def landscape(root, *args):
        # First build per root: 20 units; after a "model refresh": 5 units.
        units = 20 if root not in built else 5
        built[root] = built.get(root, 0) + 1
        view = SWEEP.SliceLandscape(root, units, 0.1)
        view.finalize({})
        return view

    def planner(landscape, budget, **kwargs):
        return [landscape.total_units - 2], []

    backend = ScriptedBackend(lambda ps, p: [path("a", 15.0), path("b", 5.0)], True)
    params = SimpleNamespace(TimingParamsLookupTable=fresh(ps), auto_multi_cycle_ncycles={})
    with tempfile.TemporaryDirectory() as out, ExitStack() as stack:
        extra = [
            (SYN, "SYN_OUTPUT_DIRECTORY", out),
            (SWEEP, "BUILD_SLICE_LANDSCAPE", landscape),
            (SWEEP, "PLAN_PIPELINE_PLACEMENTS", planner),
        ]
        for obj, key, value in _scripted_sweep_patches(backend, fresh, extra):
            stack.enter_context(patch.object(obj, key, value))
        result = SWEEP.DO_PLANNED_THROUGHPUT_SWEEP(ps, params)
    assert built["b"] == 1, built  # the replaying MAIN kept its first landscape
    assert built["a"] > 1, built  # the failing MAIN replanned on the new model
    failing = {f[0] for f in result.sweep_timing_failures}
    assert failing == {"a"}, result.sweep_timing_failures


def test_fresh_concrete_candidate_is_tried_before_measured_fallback():
    """A stagnant MAIN that just received a new concrete lock is not yet
    stagnant: the lock is synthesized first, and the broad measured fallback
    runs only if stagnation persists (the 40 MHz run measured 25 functions
    before trying two fresh locks that then met)."""
    from unittest.mock import patch
    from contextlib import ExitStack
    from scripted_sweep_backend import ScriptedBackend, path
    import SYN

    marker = SWEEP.C_TO_LOGIC.SUBMODULE_MARKER
    main, helper = FakeLogic("a"), FakeLogic("h_a")
    main.submodule_instances = {"h": "h_a"}
    child = "a" + marker + "h"
    ps = FakeParserState({"a": main, child: helper})
    ps.main_mhz = {"a": 100}
    ps.FuncToInstances = {"a": {"a"}, "h_a": {child}}
    main.delay, main.delay_is_estimated = 200, False
    helper.delay, helper.delay_is_estimated = 150, True  # an estimate is in play

    def fresh(_):
        return {i: AUTO_PIPELINE.TimingParams(i, l) for i, l in ps.LogicInstLookupTable.items()}

    def mini(func, plan, ps_):
        table = fresh(ps_)
        table[child].SET_SLICES([0.5])
        plan.locked[child] = SWEEP.MiniSweepLock(
            [0.5],
            concrete=AUTO_PIPELINE.CAPTURE_CONCRETE_PIPELINE(child, table, ps_),
            model_fingerprint=SWEEP.SUBTREE_MODEL_FINGERPRINT(child, ps_),
        )
        return True

    measured = []

    def measure(funcs, ps_):
        measured.append(list(funcs))
        for f in funcs:
            ps_.FuncLogicLookupTable[f].delay_is_estimated = False

    def rule(ps_, params):
        locked = len(params.TimingParamsLookupTable[child]._slices) > 0
        return [path("a", 5.0 if locked else 15.0)]

    backend = ScriptedBackend(rule, True)
    params = SimpleNamespace(TimingParamsLookupTable=fresh(ps), auto_multi_cycle_ncycles={})
    with tempfile.TemporaryDirectory() as out, ExitStack() as stack:
        extra = [
            (SYN, "SYN_OUTPUT_DIRECTORY", out),
            (SYN, "MEASURE_DELAYS", measure),
            (SYN, "HIER_SYN_MODE", "leaf"),
            (SWEEP, "RUN_HOTSPOT_MINISWEEP", mini),
            (SWEEP, "RESOLVE_PIPELINABLE_HOTSPOT", lambda p_, plan, ps_: ("h_a", None, "")),
            (AUTO_PIPELINE, "ADDED_LATENCY_BLOCKER", lambda *a: None),
            (AUTO_PIPELINE, "FUNC_HAS_HIER_ALLOWING_ADDED_LATENCY_TO_RAW_VHDL", lambda *a: True),
            (
                AUTO_PIPELINE.TimingParams,
                "GET_TOTAL_LATENCY",
                lambda self, _ps, t: sum(
                    len(t[i]._slices) for i in t
                    if i == self.inst_name or i.startswith(self.inst_name + marker)
                ),
            ),
            (
                SWEEP,
                "SUMMARIZE_SUBTREE_PIPELINE",
                lambda m, st, t, p_: (False, [], len(t[child]._slices)),
            ),
            (
                SWEEP,
                "GET_SUBTREE_PIPELINE_STAGES",
                lambda plan, t, p_: len(t[child]._slices),
            ),
        ]
        for obj, key, value in _scripted_sweep_patches(backend, fresh, extra):
            stack.enter_context(patch.object(obj, key, value))
        result = SWEEP.DO_PLANNED_THROUGHPUT_SWEEP(ps, params)
    assert not result.sweep_timing_failures, result.sweep_timing_failures
    assert len(result.TimingParamsLookupTable[child]._slices) == 1
    # The fresh lock met: the broad fallback was never needed.
    assert measured == [], measured
    assert len(backend.calls) == 2, backend.calls


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
