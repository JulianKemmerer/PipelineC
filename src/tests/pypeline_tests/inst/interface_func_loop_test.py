# pyright: reportInvalidTypeForm=none
"""Feedforward loops + multi-output callees -- the FSM+datapath merge shape.

The generated wiring rule is direction-agnostic: an edge gets a `Feedback[T]`
whenever its source is emitted *after* the destination that consumes it. That
inserts a feedback on a reverse edge (ordinary backpressure) and equally on a
*feedforward* edge, which is what lets an FSM consume a value produced by a
pipeline called after it:

    fsm.to_pipe -> pipe -> back into fsm.from_pipe

This is the structure of wireguard's chacha20_instance / poly1305_mac_instance,
which hand-thread exactly these two Feedbacks. Checked against a hand-written
explicit twin, cycle for cycle.
"""
import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "..",
        "..",
        "include",
        "pypeline",
    ),
)
from pypeline import (
    MAIN,
    Reg,
    hw_func,
    struct,
    NamedTuple,
    Feedback,
    uint1_t,
    uint8_t,
    sim_call,
    sim_reset,
)
from interface.interface import (
    interface,
    make_interface_type,
    make_interface_feedback_type,
)
from interface.interface_func import make_hw_func_from_interface_func


@interface
class chan(NamedTuple):
    data: uint8_t
    valid: uint1_t
    ready: Feedback[uint1_t]


chan_t = make_interface_type(chan)
chan_fb_t = make_interface_feedback_type(chan)


# ── a multi-output element: 2 input ports, 2 output ports ──
@struct
class fsm_t(NamedTuple):
    axis_in: chan_fb_t  # reverse of input port axis_in
    from_pipe: chan_fb_t  # reverse of input port from_pipe
    axis_out: chan_t  # feedforward of output port axis_out
    to_pipe: chan_t  # feedforward of output port to_pipe


@hw_func
def fsm(
    axis_in: chan_t, from_pipe: chan_t, axis_out: chan_fb_t, to_pipe: chan_fb_t
) -> fsm_t:
    """Routes input out to the pipeline and the pipeline's result to the output."""
    o: fsm_t
    o.to_pipe.data = axis_in.data
    o.to_pipe.valid = axis_in.valid
    o.axis_out.data = from_pipe.data
    o.axis_out.valid = from_pipe.valid
    o.axis_in.ready = to_pipe.ready
    o.from_pipe.ready = axis_out.ready
    return o


# ── the datapath the FSM loops through (registered, so the loop is breakable) ──
@struct
class pipe_t(NamedTuple):
    stream_in: chan_fb_t
    stream_out: chan_t


@hw_func
def pipe(stream_in: chan_t, stream_out: chan_fb_t) -> pipe_t:
    o: pipe_t
    o.stream_out.data = stream_in.data + 1
    o.stream_out.valid = stream_in.valid
    o.stream_in.ready = stream_out.ready
    return o


# ── the sugar: `p` is referenced before it is assigned, i.e. a feedforward loop ──
def merge(axis_in: chan) -> chan:
    f = fsm(axis_in, p.stream_out)  # consumes a value produced by a later call
    p = pipe(f.to_pipe)
    return f.axis_out


merge_inst, merge_inst_t = make_hw_func_from_interface_func(merge)


@MAIN
def top_loop(axis_in: chan_t, out_port: chan_fb_t) -> merge_inst_t:
    return merge_inst(axis_in, out_port)


# ── hand-written explicit twin: both Feedbacks written out by hand ──
@hw_func
def merge_twin(axis_in: chan_t, out_port: chan_fb_t) -> fsm_t:
    pipe_out: Feedback[chan_t]  # feedforward fed backward -- the loop
    pipe_in_rev: Feedback[chan_fb_t]  # reverse fed backward -- backpressure
    f = fsm(axis_in, pipe_out, out_port, pipe_in_rev)
    p = pipe(f.to_pipe, f.from_pipe)
    pipe_out = p.stream_out
    pipe_in_rev = p.stream_in
    return f


@MAIN
def top_twin(axis_in: chan_t, out_port: chan_fb_t) -> fsm_t:
    return merge_twin(axis_in, out_port)


def test_generated_wiring_has_both_feedback_directions():
    """The loop needs two Feedbacks: one carrying the feedforward value backward
    (fsm's from_pipe) and one carrying the reverse value backward (to_pipe's)."""
    src = merge_inst.generated_source
    assert src.count("Feedback[") == 2, src
    # both are driven from the later call, after it is emitted
    assert "= p.stream_out" in src, src
    assert "= p.stream_in" in src, src


def test_loop_matches_hand_written_twin():
    sim_reset()
    for data, valid, rdy in [(10, 1, 1), (0, 0, 1), (200, 1, 0), (7, 1, 1), (255, 1, 1)]:
        s = sim_call(top_loop, chan_t(data=data, valid=valid), chan_fb_t(ready=rdy))
        t = sim_call(top_twin, chan_t(data=data, valid=valid), chan_fb_t(ready=rdy))
        # data makes it round the loop through the +1 datapath
        assert int(s.out_port.data) == int(t.axis_out.data) == (data + 1) & 0xFF
        assert int(s.out_port.valid) == int(t.axis_out.valid) == valid
        # backpressure propagates back out of the loop
        assert int(s.axis_in.ready) == int(t.axis_in.ready) == rdy


if __name__ == "__main__":
    test_generated_wiring_has_both_feedback_directions()
    test_loop_matches_hand_written_twin()
    print("OK: feedforward loop + multi-output callee match hand-written twin")
