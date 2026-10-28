#!/usr/bin/env python3
"""SYN.PHASE charges wall time to named build phases, nested phases to
themselves only, and ELAPSED_SUMMARY_STR reports them on a second line. The
WireGuard 80 MHz builds spent half or more of their wall time outside Vivado,
and nothing said where; this is the report that does."""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../"))

import SYN


def test_nested_phases_charge_exclusive_time():
    clock = iter([0.0, 1.0, 4.0, 10.0])
    with patch.object(SYN, "timer", lambda: next(clock)), patch.dict(
        SYN.PHASE_SECONDS, {}, clear=True
    ):
        with SYN.PHASE("schedule search"):
            with SYN.PHASE("whole-design synthesis"):
                pass
        assert SYN.PHASE_SECONDS == {
            "schedule search": 7.0,
            "whole-design synthesis": 3.0,
        }, SYN.PHASE_SECONDS


def test_summary_lists_phases_longest_first():
    with patch.dict(
        SYN.PHASE_SECONDS, {"re-elaboration": 60.0, "schedule search": 3600.0}, clear=True
    ):
        summary = SYN.ELAPSED_SUMMARY_STR()
    first, second = summary.split("\n")
    assert first.startswith("Total elapsed time: "), summary
    assert second == "Time by build phase: schedule search 1:00:00, re-elaboration 0:01:00", summary


def test_phased_decorator_charges_the_whole_call():
    clock = iter([5.0, 7.5])

    @SYN.PHASED("per-function delay measurement")
    def measure(value):
        return value + 1

    with patch.object(SYN, "timer", lambda: next(clock)), patch.dict(
        SYN.PHASE_SECONDS, {}, clear=True
    ):
        assert measure(1) == 2
        assert SYN.PHASE_SECONDS == {"per-function delay measurement": 2.5}


if __name__ == "__main__":
    test_nested_phases_charge_exclusive_time()
    test_summary_lists_phases_longest_first()
    test_phased_decorator_charges_the_whole_call()
    print("All build phase timer tests passed.")
