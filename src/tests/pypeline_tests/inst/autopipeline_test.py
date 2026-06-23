# pyright: reportInvalidTypeForm=none
import sys, os

# Path for pypeline import
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

from typing import NamedTuple
from pypeline import (
    MAIN,
    make_autopipeline,
    struct,
    Reg,
    uint1_t,
    uint8_t,
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


def test_pipeline(x: stream_t) -> stream_t:
    rv: stream_t
    rv.data = x.data / ~x.data
    rv.valid = x.valid
    return rv


# AUTOPIPELINE-wrapped test_pipeline, with its own input and output registers.
# valid_ready_pipeline_test below calls this directly, with no autopipeline(...)
# at that call site -- the AUTOPIPELINE tagging is internal to autopipelined_test_pipeline.
autopipelined_test_pipeline = make_autopipeline(
    test_pipeline, has_input_reg=True, has_output_reg=True
)


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
