# pyright: reportInvalidTypeForm=none
"""Array interface ports -- how fan-out works.

An interface is point-to-point, so forking a stream needs a module that owns the
fork. That module's output is an *array* port: `axis_out: axis_t[n]` on the
return side paired with `axis_out: axis_fb_t[n]` on the argument side. Each element
is an independent interface, wired and back-pressured separately, so an interface
function hands `bcast.axis_out[i]` to each sink and the whole reverse array --
one ready per sink, assembled and fed back in -- is generated.

Uses the real `make_axis_broadcast_interlock` from the axis library rather than a
toy, and checks it against a hand-written explicit twin cycle for cycle.
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
from axi.axis import make_axis_interface, make_axis_broadcast_interlock

N_LANES = 2
axis_intrf = make_axis_interface(2)  # 2 byte lanes, keep+eod
axis_t = make_interface_type(axis_intrf)
axis_fb_t = make_interface_feedback_type(axis_intrf)

bcast, bcast_t = make_axis_broadcast_interlock(axis_intrf, N_LANES)


def test_array_port_is_introspected_as_one_port_of_n_elements():
    from interface.interface_func import callee_ports

    ports, params, ret_fields = callee_ports(bcast)
    assert set(ports) == {"axis_in", "axis_out"}
    assert ports["axis_in"].n is None and ports["axis_in"].direction == "in"
    assert ports["axis_out"].n == N_LANES and ports["axis_out"].direction == "out"
    # the array port declares arrays; its per-element halves stay scalar
    assert ports["axis_out"].elem_fwd_t is axis_t
    assert ports["axis_out"].elem_fb_t is axis_fb_t


# ── two sinks that back-pressure differently, so the lanes are distinguishable ──
@struct
class hold_t(NamedTuple):
    axis_in: axis_fb_t
    axis_out: axis_t


def make_hold(every):
    """Accepts a beat only every `every` cycles -- a lane-specific stall pattern."""

    @hw_func
    def hold(axis_in: axis_t, axis_out: axis_fb_t) -> hold_t:
        o: hold_t
        phase: Reg[uint8_t]
        can: uint1_t = phase == 0
        o.axis_out = axis_in
        o.axis_out.valid = axis_in.valid & can
        o.axis_in.ready = axis_out.ready & can
        if phase == (every - 1):
            phase = 0
        else:
            phase += 1
        return o

    return hold


hold_fast = make_hold(1)
hold_slow = make_hold(3)


@interface
class fork_ports(NamedTuple):
    fast: axis_intrf
    slow: axis_intrf


def fork_wiring(axis_in: axis_intrf) -> fork_ports:
    d = bcast(axis_in)  # reverse array assembled and fed back in for us
    f = hold_fast(d.axis_out[0])
    s = hold_slow(d.axis_out[1])
    return fork_ports(fast=f.axis_out, slow=s.axis_out)


fork, fork_t = make_hw_func_from_interface_func(fork_wiring)


@hw_func
def fork_twin(axis_in: axis_t, fast: axis_fb_t, slow: axis_fb_t) -> fork_t:
    o: fork_t
    f_ready: Feedback[axis_fb_t]
    s_ready: Feedback[axis_fb_t]
    sink_fb: axis_fb_t[N_LANES]
    sink_fb[0] = f_ready
    sink_fb[1] = s_ready
    d = bcast(axis_in, sink_fb)
    f = hold_fast(d.axis_out[0], fast)
    s = hold_slow(d.axis_out[1], slow)
    f_ready = f.axis_in
    s_ready = s.axis_in
    o.fast = f.axis_out
    o.slow = s.axis_out
    o.axis_in = d.axis_in
    return o


@MAIN
def top_fork(axis_in: axis_t, fast: axis_fb_t, slow: axis_fb_t) -> fork_t:
    return fork(axis_in, fast, slow)


@MAIN
def top_fork_twin(axis_in: axis_t, fast: axis_fb_t, slow: axis_fb_t) -> fork_t:
    return fork_twin(axis_in, fast, slow)


def mk(d0, d1, valid, eod=0):
    frag_t = axis_t.__annotations__["data"]
    bus_t = frag_t.__annotations__["frag"]
    return axis_t(
        data=frag_t(frag=bus_t(data=[d0, d1], keep=[1, 1]), eod=[eod]), valid=valid
    )


STIMULUS = [
    (mk(1, 2, 1), 1, 1),
    (mk(3, 4, 1), 1, 1),
    (mk(5, 6, 1), 1, 0),  # slow lane's consumer stalls too
    (mk(7, 8, 1), 0, 1),
    (mk(9, 10, 1), 1, 1),
    (mk(0, 0, 0), 1, 1),
]


def _run(top):
    sim_reset()
    out = []
    for data, fast_rdy, slow_rdy in STIMULUS:
        r = sim_call(top, data, axis_fb_t(ready=fast_rdy), axis_fb_t(ready=slow_rdy))
        out.append(
            (
                int(r.axis_in.ready),
                int(r.fast.valid),
                list(int(v) for v in r.fast.data.frag.data),
                int(r.slow.valid),
                list(int(v) for v in r.slow.data.frag.data),
            )
        )
    return out


def test_array_fanout_matches_hand_written_twin():
    assert _run(top_fork) == _run(top_fork_twin)


def test_each_lane_backpressures_independently():
    """The interlock ands every lane's ready together, and each lane's ready
    reaches it through its own array element -- not a shared one."""
    sim_reset()
    # both lanes' consumers ready, but the slow hold only accepts 1-in-3
    r = sim_call(top_fork, mk(1, 2, 1), axis_fb_t(ready=1), axis_fb_t(ready=1))
    assert int(r.axis_in.ready) == 1, "both lanes accepting on phase 0"
    r = sim_call(top_fork, mk(3, 4, 1), axis_fb_t(ready=1), axis_fb_t(ready=1))
    assert int(r.axis_in.ready) == 0, "slow lane stalled -> source stalls"
    sim_reset()
    # stalling only the fast lane's consumer must also stall the source
    r = sim_call(top_fork, mk(1, 2, 1), axis_fb_t(ready=0), axis_fb_t(ready=1))
    assert int(r.axis_in.ready) == 0, "fast lane's own array element carried it"


if __name__ == "__main__":
    test_array_port_is_introspected_as_one_port_of_n_elements()
    test_array_fanout_matches_hand_written_twin()
    test_each_lane_backpressures_independently()
    print("OK: array interface ports fan out with per-element backpressure")
