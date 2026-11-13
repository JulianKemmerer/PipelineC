# pyright: reportInvalidTypeForm=none
"""Fixture for the design diagram's types and filters (diagram_test.py,
diagram_render_test.py).

loop_main calls a generated interface function (make_hw_func_from_interface_func)
with a feedforward loop, as interface_func_loop_test.py does: its Feedback
variables carry a plain copy of the interface's .fwd_t (data flowing back to an
earlier call) and of its .fb_t (backpressure). stream_main holds a plain
{data, valid} stream (stream.make_stream_t) in a register and passes it through
a @wires function; flag_main holds a second stream type of the same class name."""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(_HERE, "..", "..", "..", "..", "include", "pypeline"))
from pypeline import (
    MAIN,
    Feedback,
    NamedTuple,
    Reg,
    hw_func,
    struct,
    uint1_t,
    uint8_t,
    uint16_t,
    wires,
)

from interface.interface import interface
from interface.interface_func import make_hw_func_from_interface_func
from stream.stream import make_stream_t


# Its .fwd_t's fields are not a byte_stream_t's: no role here comes from
# looking like the other kind
@interface
class chan_intrf(NamedTuple):
    data: uint16_t
    valid: uint1_t
    ready: Feedback[uint1_t]


@struct
class route_t(NamedTuple):
    axis_in_if: chan_intrf.fb_t
    from_pipe_if: chan_intrf.fb_t
    axis_out_if: chan_intrf.fwd_t
    to_pipe_if: chan_intrf.fwd_t


@hw_func
def route(
    axis_in_if: chan_intrf.fwd_t,
    from_pipe_if: chan_intrf.fwd_t,
    axis_out_if: chan_intrf.fb_t,
    to_pipe_if: chan_intrf.fb_t,
) -> route_t:
    """Only routes fields: a block of the user's hierarchy all the same."""
    o: route_t
    o.to_pipe_if.data = axis_in_if.data
    o.to_pipe_if.valid = axis_in_if.valid
    o.axis_out_if.data = from_pipe_if.data
    o.axis_out_if.valid = from_pipe_if.valid
    o.axis_in_if.ready = to_pipe_if.ready
    o.from_pipe_if.ready = axis_out_if.ready
    return o


@struct
class pipe_t(NamedTuple):
    stream_in_if: chan_intrf.fb_t
    stream_out_if: chan_intrf.fwd_t


@hw_func
def pipe(stream_in_if: chan_intrf.fwd_t, stream_out_if: chan_intrf.fb_t) -> pipe_t:
    o: pipe_t
    o.stream_out_if.data = stream_in_if.data + 1
    o.stream_out_if.valid = stream_in_if.valid
    o.stream_in_if.ready = stream_out_if.ready
    return o


# `p` is used before it is assigned: a feedforward loop through a Feedback
def merge(axis_in_if: chan_intrf) -> chan_intrf:
    f = route(axis_in_if, p.stream_out_if)
    p = pipe(f.to_pipe_if)
    return f.axis_out_if


merge_inst = make_hw_func_from_interface_func(merge)


@MAIN
def loop_main(
    axis_in_if: chan_intrf.fwd_t, out_port_if: chan_intrf.fb_t
) -> merge_inst.return_t:
    return merge_inst(axis_in_if, out_port_if)


byte_stream_t = make_stream_t(uint8_t)


@wires
def pass_through(s: byte_stream_t) -> byte_stream_t:
    return s


@MAIN
def stream_main(x: uint8_t) -> uint8_t:
    held: Reg[byte_stream_t]
    last: uint8_t = held.data
    s: byte_stream_t
    s.data = x
    s.valid = 1
    held = pass_through(s)
    return last


# A second stream type: both are classes named stream_t
flag_stream_t = make_stream_t(uint1_t)


@MAIN
def flag_main(b: uint1_t) -> uint1_t:
    seen: Reg[flag_stream_t]
    last: uint1_t = seen.data
    seen.data = b
    seen.valid = 1
    return last
