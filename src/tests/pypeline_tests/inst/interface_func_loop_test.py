# pyright: reportInvalidTypeForm=none
"""Feedforward loops + multi-output callees -- the FSM+datapath merge shape.

The generated wiring rule is direction-agnostic: an edge gets a `Feedback[T]`
whenever its source is emitted *after* the destination that consumes it. That
inserts a feedback on a reverse edge (ordinary backpressure) and equally on a
*feedforward* edge, which is what lets an FSM consume a value produced by a
pipeline called after it:

    fsm.to_pipe_if -> pipe -> back into fsm.from_pipe_if

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
from interface.interface import interface
from interface.interface_func import make_hw_func_from_interface_func


@interface
class chan_intrf(NamedTuple):
    data: uint8_t
    valid: uint1_t
    ready: Feedback[uint1_t]


# ── a multi-output element: 2 input ports, 2 output ports ──
@struct
class fsm_t(NamedTuple):
    axis_in_if: chan_intrf.fb_t  # reverse of input port axis_in_if
    from_pipe_if: chan_intrf.fb_t  # reverse of input port from_pipe_if
    axis_out_if: chan_intrf.fwd_t  # feedforward of output port axis_out_if
    to_pipe_if: chan_intrf.fwd_t  # feedforward of output port to_pipe_if


@hw_func
def fsm(
    axis_in_if: chan_intrf.fwd_t, from_pipe_if: chan_intrf.fwd_t, axis_out_if: chan_intrf.fb_t, to_pipe_if: chan_intrf.fb_t
) -> fsm_t:
    """Routes input out to the pipeline and the pipeline's result to the output."""
    o: fsm_t
    o.to_pipe_if.data = axis_in_if.data
    o.to_pipe_if.valid = axis_in_if.valid
    o.axis_out_if.data = from_pipe_if.data
    o.axis_out_if.valid = from_pipe_if.valid
    o.axis_in_if.ready = to_pipe_if.ready
    o.from_pipe_if.ready = axis_out_if.ready
    return o


# ── the datapath the FSM loops through (registered, so the loop is breakable) ──
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


# ── the sugar: `p` is referenced before it is assigned, i.e. a feedforward loop ──
def merge(axis_in_if: chan_intrf) -> chan_intrf:
    f = fsm(axis_in_if, p.stream_out_if)  # consumes a value produced by a later call
    p = pipe(f.to_pipe_if)
    return f.axis_out_if


merge_inst, merge_inst_t = make_hw_func_from_interface_func(merge)


@MAIN
def top_loop(axis_in_if: chan_intrf.fwd_t, out_port_if: chan_intrf.fb_t) -> merge_inst_t:
    return merge_inst(axis_in_if, out_port_if)


# ── hand-written explicit twin: both Feedbacks written out by hand ──
@struct
class merge_twin_t(NamedTuple):
    axis_in_if: chan_intrf.fb_t  # reverse of input port axis_in_if
    out_port_if: chan_intrf.fwd_t  # feedforward of output port out_port_if, named to match its
    # own arg (unlike fsm_t's "axis_out_if", which names the FSM's own port)


@hw_func
def merge_twin(axis_in_if: chan_intrf.fwd_t, out_port_if: chan_intrf.fb_t) -> merge_twin_t:
    pipe_out: Feedback[chan_intrf.fwd_t]  # feedforward fed backward -- the loop
    pipe_in_rev: Feedback[chan_intrf.fb_t]  # reverse fed backward -- backpressure
    f = fsm(axis_in_if, pipe_out, out_port_if, pipe_in_rev)
    p = pipe(f.to_pipe_if, f.from_pipe_if)
    pipe_out = p.stream_out_if
    pipe_in_rev = p.stream_in_if
    o: merge_twin_t
    o.axis_in_if = f.axis_in_if
    o.out_port_if = f.axis_out_if
    return o


@MAIN
def top_twin(axis_in_if: chan_intrf.fwd_t, out_port_if: chan_intrf.fb_t) -> merge_twin_t:
    return merge_twin(axis_in_if, out_port_if)


def test_generated_wiring_has_both_feedback_directions():
    """The loop needs two Feedbacks: one carrying the feedforward value backward
    (fsm's from_pipe_if) and one carrying the reverse value backward (to_pipe_if's)."""
    src = merge_inst.generated_source
    assert src.count("Feedback[") == 2, src
    # both are driven from the later call, after it is emitted
    assert "= p.stream_out_if" in src, src
    assert "= p.stream_in_if" in src, src


def test_loop_matches_hand_written_twin():
    sim_reset()
    for data, valid, rdy in [(10, 1, 1), (0, 0, 1), (200, 1, 0), (7, 1, 1), (255, 1, 1)]:
        s = sim_call(top_loop, chan_intrf.fwd_t(data=data, valid=valid), chan_intrf.fb_t(ready=rdy))
        t = sim_call(top_twin, chan_intrf.fwd_t(data=data, valid=valid), chan_intrf.fb_t(ready=rdy))
        # data makes it round the loop through the +1 datapath
        assert int(s.out_port_if.data) == int(t.out_port_if.data) == (data + 1) & 0xFF
        assert int(s.out_port_if.valid) == int(t.out_port_if.valid) == valid
        # backpressure propagates back out of the loop
        assert int(s.axis_in_if.ready) == int(t.axis_in_if.ready) == rdy


if __name__ == "__main__":
    test_generated_wiring_has_both_feedback_directions()
    test_loop_matches_hand_written_twin()
    print("OK: feedforward loop + multi-output callee match hand-written twin")
