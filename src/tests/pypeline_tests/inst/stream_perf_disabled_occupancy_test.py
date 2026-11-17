"""Regression for GitHub #399: an unselected occupancy probe is a no-op
when another tap is enabled, including after simulation reset. Exercise the
occupancy worker's NullTap.emptied() call without an HDL build or downstream
design. Registered in native_sim with ordinary pass/fail assertions.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "include" / "pypeline"))

from pypeline import sim_reset
from stream import stream_perf_probe as probe
from stream.stream_perf import NullTap


def test_unselected_occupancy_probe_is_noop():
    sim_reset()
    probe.REGISTRY.enable(["selected"])
    assert probe.REGISTRY.any_enabled()
    assert isinstance(probe.REGISTRY.tap("disabled.occupancy"), NullTap)
    probe._note_occupancy("disabled.occupancy", 0, 0, 0, 0, 2, 1)
    assert probe.REGISTRY.snapshot() == {}
    probe._note_hs("selected", 1, 1, None, 1)
    selected = probe.REGISTRY.snapshot()
    assert set(selected) == {"selected"}
    # Subsequent transfers and the first sample after reset stay unrecorded.
    probe._note_occupancy("disabled.occupancy", 1, 1, 0, 0, 2, 2)
    sim_reset()
    probe._note_occupancy("disabled.occupancy", 0, 0, 0, 0, 2, 3)
    assert probe.REGISTRY.active_names() == ["selected"]
    assert probe.REGISTRY.snapshot() == selected


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
