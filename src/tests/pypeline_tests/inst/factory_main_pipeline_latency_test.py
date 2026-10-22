"""Native simulation of factory-made @MAINs that reach a @pipeline_latency
function, with build timing that differs between them.

Two stateful lanes made by one factory call one pure helper `h` (which
calls a pipeline_latency(1) function) from the same source line, so native
sim models `h` with one stage graph per lane. Like the build results
`pypelinec --sim` passes (SIM.DO_OPTIONAL_SIM's pipeline_timing), the timing
handed to pypeline_sim.run_sim gives lane0's `h` an output register and
lane1's none. Every graph has the same call-site location, so only the
running MAIN's root frame tells them apart: lane0's results must arrive one
cycle after lane1's. Without the MAIN, the dispatch raised "ambiguous timing
variant".

Registered in native_sim_tests.py.
"""

import contextlib
import io
import os
import sys
import tempfile

SRC_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
sys.path.insert(0, SRC_DIR)

DESIGN = f"""
import sys
sys.path.insert(0, {SRC_DIR!r})
from pypeline import *


@pipeline_latency(1)
@hw_func
def delay_one(x: uint8_t) -> uint8_t:
    saved: Reg[uint8_t]
    rv = saved
    saved = x
    return rv


@hw_func
def h(x: uint8_t) -> uint8_t:
    return delay_one(x) + 1


def make_lane(i):
    @hw_func
    def lane():
        t: Reg[uint8_t]
        y = h(t)
        sim_print(f"lane{{i}} t={{t}} y={{y}}")
        t += 1

    return lane


lanes = [MAIN(make_lane(i), name=f"lane{{i}}") for i in range(2)]
"""


def _timing(path):
    """Default timing for every instance, as a build would hand it over, with
    an output register on lane0's h."""
    import AUTO_PIPELINE
    import LOGIC
    import PY_TO_LOGIC
    import pypeline
    import pypeline_sim

    pypeline_sim.import_design(path)
    state = PY_TO_LOGIC.ELABORATE_LIVE_ROOTS(list(pypeline._main_registry))
    timing = {}
    for name, logic in state.LogicInstLookupTable.items():
        tp = AUTO_PIPELINE.TimingParams(name, logic)
        timing[name] = [
            list(tp._slices),
            tp._has_input_regs,
            tp._has_output_regs,
            tp._exact_bit_boundaries,
            tp.logic.delay,
        ]
    h_insts = [n for n, l in state.LogicInstLookupTable.items() if l.func_name == "h"]
    assert len(h_insts) == 2, h_insts
    for name in h_insts:
        if name.split(LOGIC.SUBMODULE_MARKER)[0] == "lane0":
            timing[name][2] = True
    return {name: tuple(v) for name, v in timing.items()}


def test_lanes_dispatch_to_their_own_timing():
    import pypeline_sim

    with tempfile.TemporaryDirectory(prefix="factory_main_pipeline_latency_") as tmp:
        path = os.path.join(tmp, "pl_lanes.py")
        with open(path, "w") as f:
            f.write(DESIGN)
        timing = _timing(path)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            pypeline_sim.run_sim(path, 5, pipeline_timing=timing)
    lines = out.getvalue().splitlines()
    ys = {
        lane: [
            int(line.split("y=")[1]) for line in lines if line.startswith(lane + " ")
        ]
        for lane in ("lane0", "lane1")
    }
    # lane1: delay_one's one cycle; lane0: one more for h's output register
    assert ys["lane1"] == [1, 1, 2, 3, 4], ys
    assert ys["lane0"] == [0, 1, 1, 2, 3], ys
    print("test_lanes_dispatch_to_their_own_timing PASS")


if __name__ == "__main__":
    test_lanes_dispatch_to_their_own_timing()
    print("factory_main_pipeline_latency_test: all PASS")
