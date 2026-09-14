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
    assert on_disk["schema_version"] == SWEEP.SWEEP_HISTORY_SCHEMA_VERSION == 2
    assert on_disk["build_complete"] is True
    entry = on_disk["mains"]["planless_main"]
    assert entry["goal_mhz"] == 1.0 and len(entry["iterations"]) == 1
    final = entry["final"]
    assert final["met"] is True and final["source"] == "as_written"
    assert final["mhz_is_lower_bound"] is True and final["standalone_mhz"] == 250.0
    # Not in the final table: no depth claimed
    assert "pipeline_stages" not in final


def test_writer_skips_when_nothing_recorded():
    reset_records()
    assert SWEEP.WRITE_SWEEP_HISTORY(None, None, build_complete=True) is None


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  {t.__name__}: ok")
    print(f"All {len(tests)} sweep history record unit tests passed.")
