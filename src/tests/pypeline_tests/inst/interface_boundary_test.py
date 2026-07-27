# pyright: reportInvalidTypeForm=none
"""Crossing between the two wiring styles, in both directions.

Real designs mix them: modules whose reverse signal is *computed* from state are
written by hand as ordinary `@hw_func`s, and the straight-line wiring between
them is generated. So both boundaries have to hold:

  implied -> manual   an interface function instantiates a hand-written FSM.
                      Pairing is structural: the two halves of one port share
                      the port's name across the argument and return side.
                      No `_ready`/`ready_for_` affix is involved.

  manual -> implied   a hand-written `@hw_func` (or a top-level `@MAIN`)
                      instantiates the generated instance. Nothing is matched by
                      name at all -- it is an ordinary hw_func call, so the
                      reverse halves go in as arguments and come back out as
                      named return fields.

Plain non-interface signals cross both boundaries in both directions here -- a
config value going down, a status value coming back up through a mixed return
bundle -- because those are wired by a different path than interface ports and
have to keep working.

Everything is checked against a hand-written explicit twin, cycle for cycle.
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
    hw_arg_types,
    hw_return_type,
)
from interface.interface import interface
from interface.interface_func import make_hw_func_from_interface_func


@interface
class chan_intrf(NamedTuple):
    data: uint8_t
    valid: uint1_t
    ready: Feedback[uint1_t]


# ── the hand-written half: ready is computed from a register, so this can never
#    be sugar. Note the plain `limit` input and the plain `passed` output ──
@struct
class gate_t(NamedTuple):
    stream_in_if: chan_intrf.fb_t  # input port's reverse half travels out
    stream_out_if: chan_intrf.fwd_t  # output port's feedforward half travels out
    passed: uint8_t  # plain status, no reverse companion


@hw_func
def gate(stream_in_if: chan_intrf.fwd_t, limit: uint8_t, stream_out_if: chan_intrf.fb_t) -> gate_t:
    o: gate_t
    count: Reg[uint8_t]
    # closes once `limit` beats have gone through: backpressure from state
    accepting: uint1_t = count < limit
    o.stream_out_if.data = stream_in_if.data + 1
    o.stream_out_if.valid = stream_in_if.valid & accepting
    o.stream_in_if.ready = stream_out_if.ready & accepting
    if stream_in_if.valid & o.stream_in_if.ready:
        count += 1
    o.passed = count
    return o


# ── crossing: implied -> manual. Two hand-written gates chained; the reverse
#    direction between them is generated, and `limit` fans out as a plain value ──
@interface
class gated_ports(NamedTuple):
    stream_out_if: chan_intrf
    passed: uint8_t  # plain field riding along in a mixed bundle


def gated_wiring(stream_in_if: chan_intrf, limit: uint8_t) -> gated_ports:
    a = gate(stream_in_if, limit)
    b = gate(a.stream_out_if, limit)
    return gated_ports(stream_out_if=b.stream_out_if, passed=b.passed)


gated, gated_t = make_hw_func_from_interface_func(gated_wiring)


def test_generated_port_shape_is_the_documented_one():
    """args = params (interface ones as their feedforward half) then one
    feedback arg per output port; return = feedforward per output port, then
    plain bundle fields, then feedback per input port. All named by port."""
    assert hw_arg_types(gated) == (chan_intrf.fwd_t, uint8_t, chan_intrf.fb_t)
    assert list(gated_t._fields) == ["stream_out_if", "passed", "stream_in_if"]
    assert gated_t.__annotations__["stream_out_if"] is chan_intrf.fwd_t
    assert gated_t.__annotations__["stream_in_if"] is chan_intrf.fb_t
    assert gated_t.__annotations__["passed"] is uint8_t
    assert hw_return_type(gated) is gated_t


# ── crossing: manual -> implied. A hand-written module instantiates the
#    generated instance and threads the implied reverse back out to explicit
#    scalar ports -- the shape every top-level @MAIN ends up with ──
@struct
class wrapper_t(NamedTuple):
    upstream_ready: uint1_t
    out_data: uint8_t
    out_valid: uint1_t
    passed: uint8_t


@hw_func
def wrapper(
    in_data: uint8_t, in_valid: uint1_t, limit: uint8_t, downstream_ready: uint1_t
) -> wrapper_t:
    o: wrapper_t
    # .fwd_t/.fb_t may never be a local variable's declared type -- construct
    # each half inline, directly in the call arguments, at the exact point it
    # crosses into a real port.
    r = gated(
        chan_intrf.fwd_t(data=in_data, valid=in_valid),  # feedforward half in
        limit,  # plain value straight through
        chan_intrf.fb_t(ready=downstream_ready),  # reverse half of the output port
    )
    o.upstream_ready = r.stream_in_if.ready  # implied feedback -> explicit
    o.out_data = r.stream_out_if.data
    o.out_valid = r.stream_out_if.valid
    o.passed = r.passed  # plain status back across the boundary
    return o


# ── the same design with every wire written out by hand ──
@hw_func
def wrapper_twin(
    in_data: uint8_t, in_valid: uint1_t, limit: uint8_t, downstream_ready: uint1_t
) -> wrapper_t:
    o: wrapper_t
    b_ready: Feedback[chan_intrf.fb_t]  # b is called after a, so a's ready comes back
    a = gate(chan_intrf.fwd_t(data=in_data, valid=in_valid), limit, b_ready)
    b = gate(a.stream_out_if, limit, chan_intrf.fb_t(ready=downstream_ready))
    b_ready = b.stream_in_if
    o.upstream_ready = a.stream_in_if.ready
    o.out_data = b.stream_out_if.data
    o.out_valid = b.stream_out_if.valid
    o.passed = b.passed
    return o


@MAIN
def top_boundary(
    in_data: uint8_t, in_valid: uint1_t, limit: uint8_t, downstream_ready: uint1_t
) -> wrapper_t:
    return wrapper(in_data, in_valid, limit, downstream_ready)


@MAIN
def top_boundary_twin(
    in_data: uint8_t, in_valid: uint1_t, limit: uint8_t, downstream_ready: uint1_t
) -> wrapper_t:
    return wrapper_twin(in_data, in_valid, limit, downstream_ready)


STIMULUS = [
    # (data, valid, limit, downstream_ready)
    (10, 1, 3, 1),
    (11, 1, 3, 1),
    (12, 1, 3, 0),  # stalled downstream
    (13, 1, 3, 1),
    (14, 1, 3, 1),  # gates have closed by now (limit reached)
    (15, 1, 9, 1),
    (16, 0, 9, 1),
]


def _run(top):
    sim_reset()
    return [
        tuple(int(v) for v in sim_call(top, *s))
        for s in STIMULUS
    ]


def test_both_crossings_match_hand_written_twin():
    assert _run(top_boundary) == _run(top_boundary_twin)


def test_plain_signals_cross_both_boundaries():
    """`limit` goes down through the generated layer into two hand-written
    modules (a plain value may fan out; an interface may not), and `passed`
    comes back up through the mixed return bundle."""
    sim_reset()
    # limit=1: exactly one beat passes each gate, then both close
    r = sim_call(top_boundary, 10, 1, 1, 1)
    assert int(r.upstream_ready) == 1
    assert int(r.passed) == 1, "plain status crossed back out of the bundle"
    r = sim_call(top_boundary, 11, 1, 1, 1)
    assert int(r.upstream_ready) == 0, "limit reached -> plain config took effect"
    assert int(r.passed) == 1, "closed gate stops counting"

    # a wider limit keeps the gates open: same plain wire, different value
    sim_reset()
    for i in range(4):
        r = sim_call(top_boundary, 20, 1, 200, 1)
        assert int(r.upstream_ready) == 1
        assert int(r.passed) == i + 1


if __name__ == "__main__":
    test_generated_port_shape_is_the_documented_one()
    test_both_crossings_match_hand_written_twin()
    test_plain_signals_cross_both_boundaries()
    print("OK: both style crossings wire up, plain signals included")
