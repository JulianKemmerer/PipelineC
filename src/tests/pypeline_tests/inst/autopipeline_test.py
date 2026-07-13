# pyright: reportInvalidTypeForm=none
import sys, os

# Path for pypeline import
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

from typing import NamedTuple
from pypeline import (
    AUTOPIPELINE,
    MAIN,
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
class valid_ready_pipeline_test_t(NamedTuple):
    pipeline_in_ready: uint1_t
    pipeline_out: stream_t


@hw_func
def test_pipeline(x: stream_t) -> stream_t:
    rv: stream_t
    rv.data = x.data / ~x.data
    rv.valid = x.valid
    return rv


# The raw AUTOPIPELINE primitive: constructed once, eagerly, at module level
# (plain Python) and captured by closure below -- which is what makes
# .latency readable here. The tool picks the depth (no depth= arg).
TEST_PIPELINE_AP = AUTOPIPELINE(test_pipeline)

# .latency reads 0 until a real synthesizing build's pin-and-confirm pass
# installs the discovered value; in native sim it stays 0 forever.
print("autopipeline_test: TEST_PIPELINE_AP.latency =", TEST_PIPELINE_AP.latency)
assert isinstance(TEST_PIPELINE_AP.latency, int)


# Inline registered-input/registered-output idiom around the AUTOPIPELINE'd
# call (what _autopipeline_with_io_regs builds for library code).
@hw_func
def autopipelined_test_pipeline(x: stream_t) -> stream_t:
    in_reg: Reg[stream_t]
    out_reg: Reg[stream_t]
    rv: stream_t = out_reg
    out_reg = TEST_PIPELINE_AP(in_reg)
    in_reg = x
    return rv


@hw_func
def valid_ready_pipeline_test(
    pipeline_in: stream_t, pipeline_out_ready: uint1_t
) -> valid_ready_pipeline_test_t:
    o: valid_ready_pipeline_test_t
    # No FIFO in this simplified example, fake back pressure
    ready_reg: Reg[uint1_t]
    o.pipeline_in_ready = ready_reg
    ready_reg = ~ready_reg
    pipeline_no_handshake_in: stream_t
    pipeline_no_handshake_in.valid = pipeline_in.valid & o.pipeline_in_ready
    pipeline_no_handshake_in.data = pipeline_in.data
    # The autopipelined submodule instance, with registered input/output
    pipeline_no_handshake_out: stream_t = autopipelined_test_pipeline(
        pipeline_no_handshake_in
    )
    # No FIFO - connect pipeline straight to output
    o.pipeline_out = pipeline_no_handshake_out
    return o


@MAIN(50.0)
def autopipelined_submodules_main(
    pipeline_in: stream_t, pipeline_out_ready: uint1_t
) -> valid_ready_pipeline_test_t:
    return valid_ready_pipeline_test(pipeline_in, pipeline_out_ready)


def test_autopipelined_submodules_sim():
    sim_reset()
    out = sim_call(autopipelined_submodules_main, stream_t(data=4, valid=1), 1)
    print(f"test_autopipelined_submodules_sim out={out}")


def test_latency_reads_zero_in_sim():
    # Native sim never synthesizes, so the latency cache stays empty and
    # .latency must read 0.
    assert TEST_PIPELINE_AP.latency == 0


if __name__ == "__main__":
    test_autopipelined_submodules_sim()
    test_latency_reads_zero_in_sim()
    print("All autopipeline tests passed.")
