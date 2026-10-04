#!/usr/bin/env python3
# In-process unit tests for sweep_history.json's per-main "final" record
# (SWEEP.BUILD_FINAL_MAIN_RECORD / RECORD_SWEEP_ITERATION /
# RECORD_SWEEP_OUTCOME / WRITE_SWEEP_HISTORY).
#
# The bug: the history was only the sweep's iteration log, so a QoR tool
# reading its last entry as "the result" got a superseded mid-sweep fmax. A
# shared encrypt+decrypt design recorded "iter 2: 62.97 MHz, 23 stages"
# and nothing after, yet met its 80 MHz goal at iteration 3 with 20 stages:
# no path report named that main in the met iteration ("assuming met"), so
# nothing was appended. Restored best/met snapshots and a pin-and-confirm
# confirmation run are likewise not "the last iteration".
#
# The build-level wiring (sweep, confirmation run, driver) is covered end to
# end by sweep_planless_test.py, sweep_unpipelinable_test.py and
# auto_pipeline_latency_test.py; these cases pin the verdict semantics.
import json
import os
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

import SWEEP
import SYN


def reset_records():
    SWEEP.SWEEP_HISTORY.clear()
    SWEEP.SWEEP_OUTCOMES.clear()
    SWEEP.SWEEP_HISTORY_RUN = 0


DEPTH_20 = {"auto_pipelined": True, "slices_built": 19, "pipeline_stages": 20}


def test_assumed_met_is_lower_bound_not_fmax():
    # The reported case: met with no measured MHz
    reset_records()
    SWEEP.NEXT_SWEEP_HISTORY_RUN()
    SWEEP.RECORD_SWEEP_ITERATION(
        "m", 80.0, {"iter": 2, "achieved_mhz": 62.972, "met": False}
    )
    rec = SWEEP.RECORD_SWEEP_ITERATION(
        "m", 80.0, {"iter": 3, "achieved_mhz": None, "met": True}
    )
    outcome = SWEEP.RECORD_SWEEP_OUTCOME("m", 80.0, "planned_sweep", record=rec)
    final = SWEEP.BUILD_FINAL_MAIN_RECORD(80.0, outcome, None, DEPTH_20)
    assert final["met"] is True
    assert final["achieved_mhz"] is None
    assert final["mhz_is_lower_bound"] is True
    assert final["lower_bound_mhz"] == 80.0
    assert final["met_basis"] == "no_failing_path_reported"
    assert (final["run"], final["iter"], final["iteration_index"]) == (1, 3, 1)
    assert final["pipeline_stages"] == 20 and final["slices_built"] == 19


def test_measured_met_is_not_lower_bound():
    reset_records()
    rec = SWEEP.RECORD_SWEEP_ITERATION(
        "m", 80.0, {"iter": 1, "achieved_mhz": 93.69, "met": True}
    )
    outcome = SWEEP.RECORD_SWEEP_OUTCOME("m", 80.0, "planned_sweep", record=rec)
    final = SWEEP.BUILD_FINAL_MAIN_RECORD(80.0, outcome, None, DEPTH_20)
    assert final["met"] is True
    assert final["achieved_mhz"] == 93.69
    assert final["mhz_is_lower_bound"] is False
    assert final["lower_bound_mhz"] is None
    assert final["met_basis"] == "measured"


def test_timing_failure_overrides_outcome():
    # sweep_timing_failures gates the exit code, so it decides the verdict
    # and supplies the achieved MHz and reason
    outcome = {"source": "planned_sweep", "achieved_mhz": 70.0, "iter": 4}
    failure = ("m", 80.0, 72.5, "iteration_limit")
    final = SWEEP.BUILD_FINAL_MAIN_RECORD(80.0, outcome, failure, DEPTH_20)
    assert final["met"] is False
    assert final["achieved_mhz"] == 72.5
    assert final["mhz_is_lower_bound"] is False
    assert final["met_basis"] == "timing_failure"
    assert final["failure_reason"] == "iteration_limit"
    # A failure with unknown MHz keeps the outcome's measured number
    final = SWEEP.BUILD_FINAL_MAIN_RECORD(
        80.0, outcome, ("m", 80.0, None, "x"), DEPTH_20
    )
    assert final["met"] is False and final["achieved_mhz"] == 70.0


def test_confirmation_supersedes_sweep_and_iterations_accumulate():
    reset_records()
    SWEEP.NEXT_SWEEP_HISTORY_RUN()
    sweep_rec = SWEEP.RECORD_SWEEP_ITERATION(
        "m", 80.0, {"iter": 1, "achieved_mhz": 85.0, "met": True}
    )
    SWEEP.RECORD_SWEEP_OUTCOME(
        "m", 80.0, "as_written", record=sweep_rec, standalone_mhz=85.77
    )
    SWEEP.NEXT_SWEEP_HISTORY_RUN()
    confirm_rec = SWEEP.RECORD_SWEEP_ITERATION(
        "m", 80.0, {"iter": 1, "achieved_mhz": 93.69, "met": True}
    )
    SWEEP.RECORD_SWEEP_OUTCOME(
        "m", 80.0, "confirmation_run", record=confirm_rec, standalone_mhz=85.77
    )
    iterations = SWEEP.SWEEP_HISTORY["m"]["iterations"]
    assert [(r["run"], r["index"]) for r in iterations] == [(1, 0), (2, 1)]
    final = SWEEP.BUILD_FINAL_MAIN_RECORD(80.0, SWEEP.SWEEP_OUTCOMES["m"], None, None)
    assert final["source"] == "confirmation_run"
    assert final["achieved_mhz"] == 93.69
    assert (final["run"], final["iteration_index"]) == (2, 1)
    assert final["standalone_mhz"] == 85.77


def test_restored_snapshot_keeps_its_iteration():
    # The outcome is built from the record of the iteration whose table was
    # kept, not from whatever iteration ran last
    reset_records()
    best = SWEEP.RECORD_SWEEP_ITERATION(
        "m", 100.0, {"iter": 2, "achieved_mhz": 98.0, "met": False}
    )
    SWEEP.RECORD_SWEEP_ITERATION(
        "m", 100.0, {"iter": 3, "achieved_mhz": 91.0, "met": False}
    )
    outcome = SWEEP.RECORD_SWEEP_OUTCOME("m", 100.0, "planned_sweep", record=best)
    final = SWEEP.BUILD_FINAL_MAIN_RECORD(
        100.0, outcome, ("m", 100.0, 98.0, "iteration_limit"), DEPTH_20
    )
    assert final["iter"] == 2 and final["iteration_index"] == 0
    assert final["achieved_mhz"] == 98.0


def test_unverified_and_goalless_have_no_verdict():
    final = SWEEP.BUILD_FINAL_MAIN_RECORD(
        80.0, {"source": "no_sweep", "predicted_mhz": 81.0}, None, DEPTH_20
    )
    assert final["met"] is None and final["met_basis"] == "unverified"
    assert final["mhz_is_lower_bound"] is False
    assert final["predicted_mhz"] == 81.0
    final = SWEEP.BUILD_FINAL_MAIN_RECORD(None, {"source": "coarse_sweep"}, None, None)
    assert final["met"] is None and final["met_basis"] == "no_goal"
    # Nothing recorded at all is not silently a pass
    final = SWEEP.BUILD_FINAL_MAIN_RECORD(80.0, None, None, None)
    assert final["met"] is None and final["source"] is None


def test_writer_schema_and_planless_entry():
    reset_records()
    SWEEP.NEXT_SWEEP_HISTORY_RUN()
    rec = SWEEP.RECORD_SWEEP_ITERATION(
        "planless_main", 1.0, {"iter": 1, "achieved_mhz": None, "met": True}
    )
    SWEEP.RECORD_SWEEP_OUTCOME(
        "planless_main", 1.0, "as_written", record=rec, standalone_mhz=250.0
    )
    main_logic = SimpleNamespace(func_name="planless_main")
    parser_state = SimpleNamespace(
        main_mhz={"planless_main": 1.0},
        LogicInstLookupTable={"planless_main": main_logic},
    )
    params = SimpleNamespace(
        TimingParamsLookupTable={}, sweep_timing_failures=[], auto_multi_cycle_ncycles={}
    )
    saved = (
        SYN.SYN_OUTPUT_DIRECTORY,
        SYN.TOP_LEVEL_MODULE,
        SYN.GET_TARGET_MHZ,
        SYN.LOGIC_IS_ZERO_DELAY,
    )
    with tempfile.TemporaryDirectory() as out_dir:
        try:
            SYN.SYN_OUTPUT_DIRECTORY = out_dir
            SYN.TOP_LEVEL_MODULE = "top"
            SYN.GET_TARGET_MHZ = lambda inst, ps: ps.main_mhz[inst]
            SYN.LOGIC_IS_ZERO_DELAY = lambda logic, ps, allow_none_delay=False: False
            doc = SWEEP.WRITE_SWEEP_HISTORY(parser_state, params, build_complete=True)
            with open(os.path.join(out_dir, "top", "sweep_history.json")) as f:
                on_disk = json.load(f)
        finally:
            (
                SYN.SYN_OUTPUT_DIRECTORY,
                SYN.TOP_LEVEL_MODULE,
                SYN.GET_TARGET_MHZ,
                SYN.LOGIC_IS_ZERO_DELAY,
            ) = saved
    assert on_disk == doc
    assert on_disk["schema_version"] == SWEEP.SWEEP_HISTORY_SCHEMA_VERSION == 3
    assert on_disk["build_complete"] is True
    entry = on_disk["mains"]["planless_main"]
    assert entry["goal_mhz"] == 1.0 and len(entry["iterations"]) == 1
    final = entry["final"]
    assert final["met"] is True and final["source"] == "as_written"
    assert final["mhz_is_lower_bound"] is True and final["standalone_mhz"] == 250.0
    # Not in the final table: no depth claimed
    assert "pipeline_stages" not in final


def test_retained_observation_matches_winner_and_constraints():
    """A restored winner's retained observation is the newest one with its
    exact implementation signature: entity hash, clocks AND multi-cycle
    counts. A newer log of another implementation -- same HDL with different
    MCP constraints, or an over-capacity netlist -- never supplies it."""
    reset_records()
    SWEEP.NEXT_SWEEP_HISTORY_RUN()
    SWEEP.RECORD_SWEEP_OUTCOME("m", 50.0, "sweep", achieved_mhz=51.0)
    entity = {"hash": "_winner"}
    clock = {"mhz": 50.0}
    parser_state = SimpleNamespace(
        main_mhz={"m": 50.0},
        LogicInstLookupTable={"m": SimpleNamespace(func_name="m")},
    )
    tpl = {"m": SimpleNamespace(GET_HASH_EXT=lambda table, ps: entity["hash"])}

    def params(mcp):
        return SimpleNamespace(
            TimingParamsLookupTable=tpl,
            sweep_timing_failures=[],
            auto_multi_cycle_ncycles=dict(mcp),
        )

    def observation(signature, status, log):
        return dict(
            implementation_signature=signature,
            utilization=dict(status=status, resources={}, overutilization=[]),
            cache_hit=False,
            log_path=log,
        )

    saved = (
        SYN.SYN_OUTPUT_DIRECTORY,
        SYN.TOP_LEVEL_MODULE,
        SYN.GET_TARGET_MHZ,
        SYN.LOGIC_IS_ZERO_DELAY,
        list(SWEEP.SYNTHESIS_OBSERVATIONS),
    )
    with tempfile.TemporaryDirectory() as out_dir:
        try:
            SYN.SYN_OUTPUT_DIRECTORY = out_dir
            SYN.TOP_LEVEL_MODULE = "top"
            SYN.GET_TARGET_MHZ = lambda inst, ps: clock["mhz"]
            SYN.LOGIC_IS_ZERO_DELAY = lambda logic, ps, allow_none_delay=False: True
            winner = SWEEP.IMPLEMENTATION_SIGNATURE(parser_state, params({"k": 2}))
            other_mcp = SWEEP.IMPLEMENTATION_SIGNATURE(parser_state, params({"k": 3}))
            entity["hash"] = "_other"
            other_hdl = SWEEP.IMPLEMENTATION_SIGNATURE(parser_state, params({"k": 2}))
            entity["hash"] = "_winner"
            clock["mhz"] = 60.0
            other_clock = SWEEP.IMPLEMENTATION_SIGNATURE(parser_state, params({"k": 2}))
            clock["mhz"] = 50.0
            signatures = {winner, other_mcp, other_hdl, other_clock}
            assert len(signatures) == 4, "signature ignores HDL, clock or MCP counts"
            assert winner == SWEEP.IMPLEMENTATION_SIGNATURE(parser_state, params({"k": 2}))

            SWEEP.SYNTHESIS_OBSERVATIONS[:] = [
                observation(winner, "within_reported_limits", "winner.log"),
                observation(other_mcp, "within_reported_limits", "same_hdl_other_mcp.log"),
                observation(other_hdl, "over_capacity", "newer_failed.log"),
            ]
            doc = SWEEP.WRITE_SWEEP_HISTORY(parser_state, params({"k": 2}), build_complete=True)
            assert doc["retained_observation"]["log_path"] == "winner.log", doc["retained_observation"]
            assert doc["fit_status"] == "within_reported_limits"
            assert doc["auto_multi_cycle_ncycles"] == {"k": 2}
            assert doc["synthesis_cost"]["distinct_implementations"] == 3

            # The same winner observed twice: the newest matching log is kept.
            SWEEP.SYNTHESIS_OBSERVATIONS.append(
                observation(winner, "within_reported_limits", "winner_again.log")
            )
            doc = SWEEP.WRITE_SWEEP_HISTORY(parser_state, params({"k": 2}), build_complete=True)
            assert doc["retained_observation"]["log_path"] == "winner_again.log"

            # Same HDL, other constraints: the k=2 logs cannot stand in for it,
            # nor can the newest log's fit status.
            doc = SWEEP.WRITE_SWEEP_HISTORY(parser_state, params({"k": 4}), build_complete=False)
            assert doc["retained_observation"] is None
            assert doc["fit_status"] == "unknown", doc["fit_status"]
            assert doc["build_complete"] is False
            with open(os.path.join(out_dir, "top", "sweep_history.json")) as f:
                assert json.load(f)["build_complete"] is False
        finally:
            (
                SYN.SYN_OUTPUT_DIRECTORY,
                SYN.TOP_LEVEL_MODULE,
                SYN.GET_TARGET_MHZ,
                SYN.LOGIC_IS_ZERO_DELAY,
                SWEEP.SYNTHESIS_OBSERVATIONS[:],
            ) = saved
            reset_records()


def test_over_capacity_record_is_never_a_pass():
    """Default mode (no --stop_on_over_capacity) keeps sweeping an
    over-capacity netlist; meeting timing there is still not a pass."""
    measured = {"source": "planned_sweep", "achieved_mhz": 81.0}
    final = SWEEP.BUILD_FINAL_MAIN_RECORD(80.0, measured, None, None, "over_capacity")
    assert final["met"] is False and final["met_basis"] == "device_over_capacity"
    assert final["failure_reason"] == "device_over_capacity"
    assert final["achieved_mhz"] == 81.0
    assumed = {"source": "planned_sweep"}
    final = SWEEP.BUILD_FINAL_MAIN_RECORD(80.0, assumed, None, None, "over_capacity")
    assert final["met"] is False and final["mhz_is_lower_bound"] is False
    assert final["lower_bound_mhz"] is None
    # Fit does not change a verdict that was not a pass.
    final = SWEEP.BUILD_FINAL_MAIN_RECORD(
        80.0, measured, ("m", 80.0, 70.0, "timing_not_met"), None, "over_capacity"
    )
    assert final["met"] is False and final["met_basis"] == "timing_failure"
    for unverified in ({"source": "comb"}, {"source": "no_sweep"}):
        final = SWEEP.BUILD_FINAL_MAIN_RECORD(80.0, unverified, None, None, "over_capacity")
        assert final["met"] is None and final["met_basis"] == "unverified"
    # The --stop_on_over_capacity failure tuple names its own basis.
    final = SWEEP.BUILD_FINAL_MAIN_RECORD(
        80.0, {"source": "over_capacity"}, ("m", 80.0, None, "device_over_capacity"), None
    )
    assert final["met"] is False and final["met_basis"] == "device_over_capacity"
    # Fit evidence alone does not fail anything.
    final = SWEEP.BUILD_FINAL_MAIN_RECORD(80.0, measured, None, None, "within_reported_limits")
    assert final["met"] is True and final["met_basis"] == "measured"


def test_over_capacity_final_netlist_fails_the_build():
    """The retained (built) implementation is over capacity but met timing:
    final.met is False and sweep_timing_failures -- the exit code's list --
    gets a device_over_capacity entry. A goal-less MAIN is not blamed."""
    reset_records()
    SWEEP.NEXT_SWEEP_HISTORY_RUN()
    SWEEP.RECORD_SWEEP_OUTCOME("m", 80.0, "planned_sweep", achieved_mhz=81.0)
    SWEEP.RECORD_SWEEP_OUTCOME("goalless", None, "planned_sweep")
    goals = {"m": 80.0, "goalless": None}
    parser_state = SimpleNamespace(
        main_mhz=dict(goals),
        LogicInstLookupTable={n: SimpleNamespace(func_name=n) for n in goals},
    )
    tpl = {n: SimpleNamespace(GET_HASH_EXT=lambda table, ps: "_h") for n in goals}
    params = SimpleNamespace(
        TimingParamsLookupTable=tpl, sweep_timing_failures=[], auto_multi_cycle_ncycles={}
    )
    saved = (
        SYN.SYN_OUTPUT_DIRECTORY,
        SYN.TOP_LEVEL_MODULE,
        SYN.GET_TARGET_MHZ,
        SYN.LOGIC_IS_ZERO_DELAY,
        list(SWEEP.SYNTHESIS_OBSERVATIONS),
    )
    with tempfile.TemporaryDirectory() as out_dir:
        try:
            SYN.SYN_OUTPUT_DIRECTORY = out_dir
            SYN.TOP_LEVEL_MODULE = "top"
            SYN.GET_TARGET_MHZ = lambda inst, ps: goals[inst]
            SYN.LOGIC_IS_ZERO_DELAY = lambda logic, ps, allow_none_delay=False: True
            built = SWEEP.IMPLEMENTATION_SIGNATURE(parser_state, params)
            fits = dict(status="within_reported_limits", resources={}, overutilization=[])
            over = dict(fits, status="over_capacity")
            # Only another implementation is over capacity: nothing added.
            SWEEP.SYNTHESIS_OBSERVATIONS[:] = [
                dict(implementation_signature="other", utilization=over, cache_hit=False),
                dict(implementation_signature=built, utilization=fits, cache_hit=False),
                dict(implementation_signature="newer", utilization=over, cache_hit=False),
            ]
            assert SWEEP.ADD_OVER_CAPACITY_FAILURES(parser_state, params) == []
            doc = SWEEP.WRITE_SWEEP_HISTORY(parser_state, params, build_complete=True)
            assert doc["fit_status"] == "within_reported_limits"
            assert doc["mains"]["m"]["final"]["met"] is True

            # The built implementation itself is over capacity.
            SWEEP.SYNTHESIS_OBSERVATIONS.append(
                dict(implementation_signature=built, utilization=over, cache_hit=False)
            )
            provisional = SWEEP.WRITE_SWEEP_HISTORY(parser_state, params, build_complete=False)
            assert provisional["mains"]["m"]["final"]["met"] is False
            added = SWEEP.ADD_OVER_CAPACITY_FAILURES(parser_state, params)
            assert added == [("m", 80.0, 81.0, "device_over_capacity")], added
            assert params.sweep_timing_failures == added
            # Idempotent: an already-failing main is not added twice.
            assert SWEEP.ADD_OVER_CAPACITY_FAILURES(parser_state, params) == []
            doc = SWEEP.WRITE_SWEEP_HISTORY(parser_state, params, build_complete=True)
            assert doc["fit_status"] == "over_capacity"
            final = doc["mains"]["m"]["final"]
            assert final["met"] is False and final["met_basis"] == "device_over_capacity"
            assert doc["mains"]["goalless"]["final"]["met"] is None
            assert SWEEP.PRINT_TIMING_FAILURES(params) is True
        finally:
            (
                SYN.SYN_OUTPUT_DIRECTORY,
                SYN.TOP_LEVEL_MODULE,
                SYN.GET_TARGET_MHZ,
                SYN.LOGIC_IS_ZERO_DELAY,
                SWEEP.SYNTHESIS_OBSERVATIONS[:],
            ) = saved
            reset_records()


def test_writer_skips_when_nothing_recorded():
    reset_records()
    assert SWEEP.WRITE_SWEEP_HISTORY(None, None, build_complete=True) is None


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  {t.__name__}: ok")
    print(f"All {len(tests)} sweep history record unit tests passed.")
