# pyright: reportInvalidTypeForm=none
"""Fixture for the design diagram's types, wires and filters (diagram_test.py,
diagram_render_test.py).

loop_main calls a generated interface function (make_hw_func_from_interface_func)
with a feedforward loop, as interface_func_loop_test.py does: its Feedback
variables carry a plain copy of the interface's .fwd_t (data flowing back to an
earlier call) and of its .fb_t (backpressure). stream_main holds a plain
{data, valid} stream (stream.make_stream_t) in a register and passes it through
a @wires function; flag_main holds a second named stream type, and two more no
module-level name gives (attributes of the class held), whose classes are both
named stream_t. side_main has a forward stream in and out beside a plain
sideband input (gain), and a comparison the default soft comparator
implements. pair_main returns a struct assembled from fields, one of them
selected from another call's returned struct; pass_main returns another
call's struct whole; ctor_main passes a struct built inline as an argument;
sum_main passes two fields of one call's result to another call. link_tx_main and link_rx_main share a Wire of the
interface itself (its wire_t), ready flowing back; pair_tx_main and
pair_rx_main each write one field of a plain struct Wire and read the other.
pins_main, an I/O @wires MAIN, packs Input pins into one stream wire and
unpacks another into Output pins, beside a sideband pin (rx_key)."""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(_HERE, "..", "..", "..", "..", "include", "pypeline"))
from pypeline import (
    MAIN,
    Feedback,
    Input,
    NamedTuple,
    Output,
    Reg,
    Wire,
    hw_func,
    struct,
    uint1_t,
    uint2_t,
    uint4_t,
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


# Two stream types no module-level name gives
class held:
    narrow_t = make_stream_t(uint2_t)
    wide_t = make_stream_t(uint4_t)


@MAIN
def flag_main(b: uint1_t) -> uint1_t:
    seen: Reg[flag_stream_t]
    narrow: Reg[held.narrow_t]
    wide: Reg[held.wide_t]
    last: uint1_t = seen.data
    seen.data = b
    seen.valid = 1
    narrow.valid = b
    wide.valid = narrow.valid
    return last


@MAIN
def side_main(side_in: byte_stream_t, gain: uint8_t) -> byte_stream_t:
    o: byte_stream_t
    o.data = side_in.data + gain
    o.valid = side_in.valid
    if gain > 100:
        o.valid = 0
    return o


@struct
class pair_t(NamedTuple):
    first: uint8_t
    second: uint8_t


@hw_func
def make_pair(x: uint8_t) -> pair_t:
    o: pair_t
    o.first = x
    o.second = x + 1
    return o


@hw_func
def bump(v: uint8_t) -> uint8_t:
    return v + 1


@MAIN
def pair_main(x: uint8_t) -> pair_t:
    p = make_pair(x)
    o: pair_t
    o.first = bump(p.second)
    o.second = p.first
    return o


@MAIN
def pass_main(x: uint8_t) -> pair_t:
    return make_pair(x)


@hw_func
def add_pair(a: uint8_t, b: uint8_t) -> uint8_t:
    return a + b


@MAIN
def sum_main(x: uint8_t) -> uint8_t:
    p = make_pair(x)
    return add_pair(p.first, p.second)


@hw_func
def first_of(p: pair_t) -> uint8_t:
    return p.first


@MAIN
def ctor_main(x: uint8_t) -> uint8_t:
    return first_of(pair_t(x, x + 1))


link: Wire[chan_intrf]  # link_tx_main -> link_rx_main, ready back


@MAIN
def link_tx_main(d: uint16_t) -> uint1_t:
    link.data = d + 1
    link.valid = 1
    return link.ready


@MAIN
def link_rx_main() -> uint16_t:
    link.ready = 1
    return link.data + 1


pair_link: Wire[pair_t]  # pair_tx_main writes first, pair_rx_main second


@MAIN
def pair_tx_main(x: uint8_t) -> uint8_t:
    pair_link.first = x
    return pair_link.second


@MAIN
def pair_rx_main(y: uint8_t) -> uint8_t:
    pair_link.second = y
    return pair_link.first


rx_data: Input[uint8_t]  # with rx_valid, the stream rx_stream
rx_valid: Input[uint1_t]
rx_key: Input[uint8_t]  # sideband beside the streams
tx_data: Output[uint8_t]  # with tx_valid, the stream tx_stream
tx_valid: Output[uint1_t]
rx_stream: Wire[byte_stream_t]
tx_stream: Wire[byte_stream_t]
key: Wire[uint8_t]


@MAIN
@wires
def pins_main():
    rx_stream.data = rx_data
    rx_stream.valid = rx_valid
    key = rx_key
    tx_data = tx_stream.data
    tx_valid = tx_stream.valid


@MAIN
def stream_core_main():
    tx_stream.data = rx_stream.data + key
    tx_stream.valid = rx_stream.valid
