"""Known issue (GitHub #399): an unselected occupancy probe must be a no-op
when another tap is enabled. The occupancy worker instead calls emptied()
on NullTap and raises AttributeError. No HDL build or downstream design is
needed. Registered with expect_fail until the library bug is fixed.
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


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
