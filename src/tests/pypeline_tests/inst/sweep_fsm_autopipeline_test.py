# pyright: reportInvalidTypeForm=none
# Planned throughput sweep test (c): stateful (Reg) main containing an
# AUTOPIPELINE region (via _autopipeline_with_io_regs). The cut subtree is the
# AUTOPIPELINE tagged child; cuts descend through the stateful boundary via
# the tag override while the FSM's own latency stays 0.
import sys, os

# Path for pypeline import
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

from typing import NamedTuple
from pypeline import (
    MAIN,
    _autopipeline_with_io_regs,
    hw_func,
    struct,
    Reg,
    uint1_t,
    uint8_t,
    sim_call,
    sim_reset,
)

data_t = uint8_t


@struct
class stream_t(NamedTuple):
    data: data_t
    valid: uint1_t


@struct
class fsm_pipeline_test_t(NamedTuple):
    pipeline_in_ready: uint1_t
    pipeline_out: stream_t


@hw_func
def heavy_pipeline(x: stream_t) -> stream_t:
    rv: stream_t
    a: data_t = x.data / ~x.data
    rv.data = a / (x.data + 1)
    rv.valid = x.valid
    return rv


autopipelined_heavy_pipeline, heavy_pipeline_ap = _autopipeline_with_io_regs(
    heavy_pipeline, has_input_reg=True, has_output_reg=True
)
# Reading .latency here makes this design a .latency consumer: a real
# synthesizing build (synth_tests runs this file through a full sweep) then
# exercises the pypelinec driver's pin-and-confirm pass. 0 on the bootstrap
# pass and in native sim; the discovered core depth on the confirm pass.
print(
    "sweep_fsm_autopipeline_test: heavy_pipeline AUTOPIPELINE latency =",
    heavy_pipeline_ap.latency,
    "clks",
)


@MAIN(40.0)
def sweep_fsm_autopipeline_main(
    pipeline_in: stream_t, pipeline_out_ready: uint1_t
) -> fsm_pipeline_test_t:
    o: fsm_pipeline_test_t
    # Fake back pressure register makes this main stateful (not sliceable
    # itself) - only the tagged region can accept added latency
    ready_reg: Reg[uint1_t]
    o.pipeline_in_ready = ready_reg
    ready_reg = ~ready_reg
    gated_in: stream_t
    gated_in.valid = pipeline_in.valid & o.pipeline_in_ready
    gated_in.data = pipeline_in.data
    o.pipeline_out = autopipelined_heavy_pipeline(gated_in)
    return o


def test_sweep_fsm_autopipeline_sim():
    sim_reset()
    out = sim_call(sweep_fsm_autopipeline_main, stream_t(data=4, valid=1), 1)
    print(f"test_sweep_fsm_autopipeline_sim out={out}")


if __name__ == "__main__":
    test_sweep_fsm_autopipeline_sim()
    print("All sweep fsm autopipeline tests passed.")
