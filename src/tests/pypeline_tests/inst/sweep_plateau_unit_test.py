#!/usr/bin/env python3
# In-process unit tests for SWEEP.AT_PLATEAU, the planned sweep's
# prediction-independent plateau stop.
#
# The bug: under sky130, sweep_floor_detect_design.py at a 100 MHz goal sat
# flat at 51.42 MHz while the cut count grew 25 -> 64, but its soft-floor
# prediction (~37 MHz) was too pessimistic for AT_PREDICTED_FLOOR's band, and
# nothing else stopped a flat run: all 12 iterations ran (iteration_limit).
#
# The build-level wiring (stop reason in sweep_history.json, TIMING NOT MET)
# is covered end to end by sweep_floor_detect_test.py; these cases pin the
# detector's semantics.
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

import SWEEP


def rec(mhz, cuts, met=False):
    return {"achieved_mhz": mhz, "cuts": cuts, "met": met}


# The sky130 evidence trace, iterations 1-5 (the fallback ran after iter 5;
# iter 6 measured 51.422 MHz at 43 cuts)
HANDOFF_TRACE = [
    rec(48.991, 2),
    rec(47.956, 2),
    rec(49.358, 7),
    rec(50.597, 11),
    rec(51.422, 25),
]


def test_handoff_trace_stops_at_iter_6():
    # Iter 5 alone (window 49.36/50.60/51.42) is still improving past noise
    assert not SWEEP.AT_PLATEAU(HANDOFF_TRACE[:4], 51.422, 25, 100.0)
    # Iter 6: 50.60/51.42/51.42 is flat within 1 MHz and cuts grew 11 -> 43
    assert SWEEP.AT_PLATEAU(HANDOFF_TRACE, 51.422, 43, 100.0)


def test_still_improving_does_not_stop():
    history = [rec(40.0, 5), rec(45.0, 10)]
    assert not SWEEP.AT_PLATEAU(history, 50.0, 20, 100.0)
    # Just past noise (range == 1% of the target) still counts as moving
    history = [rec(50.0, 5), rec(50.5, 10)]
    assert not SWEEP.AT_PLATEAU(history, 51.0, 20, 100.0)


def test_flat_without_cut_growth_does_not_stop():
    history = [rec(50.0, 10), rec(50.1, 12)]
    assert not SWEEP.AT_PLATEAU(history, 50.0, 10, 100.0)
    assert not SWEEP.AT_PLATEAU(history, 50.0, 9, 100.0)


def test_short_window_does_not_stop():
    assert not SWEEP.AT_PLATEAU([], 50.0, 10, 100.0)
    assert not SWEEP.AT_PLATEAU([rec(50.0, 5)], 50.0, 10, 100.0)


def test_met_or_incomplete_record_does_not_stop():
    assert not SWEEP.AT_PLATEAU([rec(50.0, 5, met=True), rec(50.0, 7)], 50.0, 10, 100.0)
    assert not SWEEP.AT_PLATEAU(
        [{"achieved_mhz": 50.0, "met": False}, rec(50.0, 7)], 50.0, 10, 100.0
    )
    assert not SWEEP.AT_PLATEAU(
        [{"cuts": 5, "met": False}, rec(50.0, 7)], 50.0, 10, 100.0
    )


def test_only_tail_counts():
    # Older non-flat history before the window is irrelevant
    history = [rec(10.0, 1), rec(30.0, 2), rec(50.0, 5), rec(50.2, 8)]
    assert SWEEP.AT_PLATEAU(history, 50.1, 10, 100.0)


def test_window_start_slice_respected():
    # The sweep passes history[plateau_window_start:]; a structural reset
    # that leaves fewer than streak-1 records blocks the stop
    history = [rec(50.0, 5), rec(50.0, 8)]
    start = 1
    assert not SWEEP.AT_PLATEAU(history[start:], 50.0, 10, 100.0)
    assert SWEEP.AT_PLATEAU(history[0:], 50.0, 10, 100.0)


def test_streak_parameter():
    history = [rec(50.0, 5)]
    assert SWEEP.AT_PLATEAU(history, 50.0, 6, 100.0, streak=2)
    assert not SWEEP.AT_PLATEAU(history, 50.0, 6, 100.0, streak=1)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  {t.__name__}: ok")
    print(f"All {len(tests)} sweep plateau unit tests passed.")
