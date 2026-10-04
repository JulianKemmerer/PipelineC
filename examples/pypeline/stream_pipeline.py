# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none
"""A pipeline behind valid/ready stream handshakes, connected with global wires.

pipeline.py is a bare pure function. Real designs also need to say where the
pipeline's inputs come from and where its outputs go: state machines, RAMs and
other parts of the design. make_stream_auto_pipeline() wraps a pure function in an
auto-pipelined instance plus an output FIFO, behind data+valid / ready stream
handshakes. Global Wire[T]s then connect it to any other @MAIN: here a producer
feeds it, and a consumer prints its results and drives the latest one out a
top-level output port.

    pypelinec examples/pypeline/stream_pipeline.py --sim --comb --run 20
"""

from pypeline import *
from stream.stream_auto_pipeline import make_stream_auto_pipeline


# The pipeline's input: two numbers to multiply
@struct
class mult_in_t(NamedTuple):
    x: uint16_t
    y: uint16_t


# A pure function (no Reg[T] state), so it can be auto-pipelined
@hw_func
def mult(i: mult_in_t) -> uint32_t:
    return i.x * i.y


# One instance of mult(), auto-pipelined, behind stream handshakes
mult_pipeline, mult_pipeline_t = make_stream_auto_pipeline(mult)
in_intrf = mult_pipeline.in_intrf
out_intrf = mult_pipeline.out_intrf

# Globally visible wires to interface with the pipeline
mult_in: Wire[in_intrf.stream_t]  # input to pipeline, data+valid
mult_in_ready: Wire[uint1_t]  # output from pipeline, ready
mult_out: Wire[out_intrf.stream_t]  # output from pipeline, data+valid
mult_out_ready: Wire[uint1_t]  # input to pipeline, ready


@MAIN(100.0)
def mult_pipeline_main():
    result = mult_pipeline(
        in_intrf.fwd_t(stream=mult_in), out_intrf.fb_t(ready=mult_out_ready)
    )
    mult_out = result.stream_out_if.stream
    mult_in_ready = result.stream_in_if.ready


# Feeds the pipeline: x*(x+1) for x = 0, 1, 2, ...
@MAIN(100.0)
def producer():
    x: Reg[uint16_t]
    mult_in.data.x = x
    mult_in.data.y = x + 1
    mult_in.valid = 1
    if mult_in_ready:  # input accepted: valid and ready this cycle
        x += 1


# Top-level output port: the most recent result
result_out: Output[uint32_t]


# Uses the pipeline's results
@MAIN(100.0)
def consumer():
    last_result: Reg[uint32_t]
    mult_out_ready = 1  # always ready
    if mult_out.valid:
        sim_print(f"Result: {mult_out.data}")
        last_result = mult_out.data
    result_out = last_result
