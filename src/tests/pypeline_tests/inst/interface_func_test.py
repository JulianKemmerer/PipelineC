# pyright: reportInvalidTypeForm=none
"""Interface functions: feedforward-only bodies, reverse direction generated.

Covers a two-stage chain against a hand-written explicit twin (proving the
generated reverse wiring matches what a person would write by hand), multi-in/
multi-out bundles, a multi-field non-bit reverse channel, plain (non-interface)
pass-through and plain intermediate statements, nested bundles, composition +
memoization, and every rejection. The feedforward-loop / multi-output-callee
capability lives in interface_func_loop_test.py.
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
    hw_func,
    struct,
    NamedTuple,
    Feedback,
    uint1_t,
    uint2_t,
    uint8_t,
    sim_call,
    sim_reset,
)
from interface.interface import interface
from interface.interface_func import (
    InterfaceError,
    callee_ports,
    make_hw_func_from_interface_func,
)


@interface
class chan_intrf(NamedTuple):
    data: uint8_t
    valid: uint1_t
    ready: Feedback[uint1_t]


def make_inc(k):
    """A combinational element declared with the interface's split structs."""

    @struct
    class inc_t(NamedTuple):
        stream_in_if: chan_intrf.fb_t  # input port's reverse half travels out
        stream_out_if: chan_intrf.fwd_t  # output port's feedforward half travels out

    @hw_func
    def inc(stream_in_if: chan_intrf.fwd_t, stream_out_if: chan_intrf.fb_t) -> inc_t:
        o: inc_t
        o.stream_out_if.data = stream_in_if.data + k
        o.stream_out_if.valid = stream_in_if.valid
        o.stream_in_if.ready = stream_out_if.ready
        return o

    return inc, inc_t


inc2, inc2_t = make_inc(2)
inc5, inc5_t = make_inc(5)


def test_ports_introspected_structurally():
    """Direction comes from which side holds the feedforward half -- no name
    convention is consulted, so port names are arbitrary."""
    ports, _params, _ret = callee_ports(inc2)
    assert {n: p.direction for n, p in ports.items()} == {
        "stream_in_if": "in",
        "stream_out_if": "out",
    }


# ── two-stage chain: sugar vs hand-written explicit twin ──
def series(stream_in_if: chan_intrf) -> chan_intrf:
    a = inc2(stream_in_if)
    b = inc5(a.stream_out_if)
    return b.stream_out_if


series_inst, series_inst_t = make_hw_func_from_interface_func(series)


@MAIN
def top_sugar(stream_in_if: chan_intrf.fwd_t, out_port_if: chan_intrf.fb_t) -> series_inst_t:
    return series_inst(stream_in_if, out_port_if)


@struct
class series_twin_t(NamedTuple):
    stream_in_if: chan_intrf.fb_t  # input port's reverse half travels out
    out_port_if: chan_intrf.fwd_t  # output port's feedforward half travels out, named to
    # match its own arg (unlike inc5_t's "stream_out_if", which names its
    # source-module's port instead)


@hw_func
def series_twin(stream_in_if: chan_intrf.fwd_t, out_port_if: chan_intrf.fb_t) -> series_twin_t:
    rev: Feedback[chan_intrf.fb_t]
    a = inc2(stream_in_if, rev)
    b = inc5(a.stream_out_if, out_port_if)
    rev = b.stream_in_if
    o: series_twin_t
    o.out_port_if = b.stream_out_if
    o.stream_in_if = a.stream_in_if
    return o


@MAIN
def top_twin(stream_in_if: chan_intrf.fwd_t, out_port_if: chan_intrf.fb_t) -> series_twin_t:
    return series_twin(stream_in_if, out_port_if)


def test_chain_matches_hand_written_twin():
    sim_reset()
    for data, valid, rdy in [(10, 1, 1), (0, 0, 1), (200, 1, 0), (7, 1, 1)]:
        s = sim_call(top_sugar, chan_intrf.fwd_t(data=data, valid=valid), chan_intrf.fb_t(ready=rdy))
        t = sim_call(top_twin, chan_intrf.fwd_t(data=data, valid=valid), chan_intrf.fb_t(ready=rdy))
        assert int(s.out_port_if.data) == int(t.out_port_if.data) == (data + 7) & 0xFF
        assert int(s.out_port_if.valid) == int(t.out_port_if.valid) == valid
        assert int(s.stream_in_if.ready) == int(t.stream_in_if.ready) == rdy


# ── multiple in/out via an interface bundle ──
@interface
class pair(NamedTuple):
    x_if: chan_intrf
    y_if: chan_intrf


def two_lanes(a_if: chan_intrf, b_if: chan_intrf) -> pair:
    p = inc2(a_if)
    q = inc5(b_if)
    return pair(x_if=p.stream_out_if, y_if=q.stream_out_if)


lanes_inst, lanes_inst_t = make_hw_func_from_interface_func(two_lanes)


@MAIN
def top_lanes(
    a_if: chan_intrf.fwd_t, b_if: chan_intrf.fwd_t, x_if: chan_intrf.fb_t, y_if: chan_intrf.fb_t
) -> lanes_inst_t:
    return lanes_inst(a_if, b_if, x_if, y_if)


def test_multi_in_out_bundle():
    sim_reset()
    r = sim_call(
        top_lanes,
        chan_intrf.fwd_t(data=10, valid=1),
        chan_intrf.fwd_t(data=20, valid=0),
        chan_intrf.fb_t(ready=1),
        chan_intrf.fb_t(ready=0),
    )
    assert int(r.x_if.data) == 12 and int(r.x_if.valid) == 1
    assert int(r.y_if.data) == 25 and int(r.y_if.valid) == 0
    # each lane's reverse half is routed back independently
    assert int(r.a_if.ready) == 1 and int(r.b_if.ready) == 0


# ── a non-uint1_t reverse channel, and >1 reverse field ──
@interface
class credit_chan_intrf(NamedTuple):
    data: uint8_t
    valid: uint1_t
    credit: Feedback[uint2_t]
    halt: Feedback[uint1_t]


@struct
class cpass_t(NamedTuple):
    stream_in_if: credit_chan_intrf.fb_t
    stream_out_if: credit_chan_intrf.fwd_t


@hw_func
def cpass(stream_in_if: credit_chan_intrf.fwd_t, stream_out_if: credit_chan_intrf.fb_t) -> cpass_t:
    o: cpass_t
    o.stream_out_if.data = stream_in_if.data + 1
    o.stream_out_if.valid = stream_in_if.valid
    o.stream_in_if.credit = stream_out_if.credit
    o.stream_in_if.halt = stream_out_if.halt
    return o


def credit_series(s_if: credit_chan_intrf) -> credit_chan_intrf:
    a = cpass(s_if)
    b = cpass(a.stream_out_if)
    return b.stream_out_if


cs_inst, cs_inst_t = make_hw_func_from_interface_func(credit_series)


@MAIN
def top_credit(s_if: credit_chan_intrf.fwd_t, out_port_if: credit_chan_intrf.fb_t) -> cs_inst_t:
    return cs_inst(s_if, out_port_if)


def test_multi_field_non_bit_reverse():
    sim_reset()
    r = sim_call(top_credit, credit_chan_intrf.fwd_t(data=5, valid=1), credit_chan_intrf.fb_t(credit=2, halt=1))
    assert int(r.out_port_if.data) == 7
    # the whole multi-field reverse bundle is threaded back, not just one bit
    assert int(r.s_if.credit) == 2 and int(r.s_if.halt) == 1


# ── plain (non-interface) values: params, and a plain intermediate statement ──
@struct
class scale_t(NamedTuple):
    stream_in_if: chan_intrf.fb_t
    stream_out_if: chan_intrf.fwd_t


@hw_func
def scale(stream_in_if: chan_intrf.fwd_t, k: uint8_t, stream_out_if: chan_intrf.fb_t) -> scale_t:
    o: scale_t
    o.stream_out_if.data = stream_in_if.data + k
    o.stream_out_if.valid = stream_in_if.valid
    o.stream_in_if.ready = stream_out_if.ready
    return o


def with_plain(a_if: chan_intrf, k: uint8_t) -> chan_intrf:
    kk: uint8_t = k + 1  # plain statement: copied through verbatim
    m = scale(a_if, kk)
    return m.stream_out_if


plain_inst, plain_inst_t = make_hw_func_from_interface_func(with_plain)


@MAIN
def top_plain(a_if: chan_intrf.fwd_t, k: uint8_t, out_port_if: chan_intrf.fb_t) -> plain_inst_t:
    return plain_inst(a_if, k, out_port_if)


def test_plain_values_pass_through():
    # a non-interface param rides through with no reverse companion
    assert "k" not in plain_inst_t._fields
    sim_reset()
    r = sim_call(top_plain, chan_intrf.fwd_t(data=10, valid=1), 4, chan_intrf.fb_t(ready=1))
    assert int(r.out_port_if.data) == 15  # 10 + (4+1)
    assert int(r.a_if.ready) == 1


# ── composition: an interface function calling another ──
def inner(s_if: chan_intrf) -> chan_intrf:
    a = inc2(s_if)
    return a.stream_out_if


def outer(s_if: chan_intrf) -> chan_intrf:
    x = inner(s_if)
    y = inc5(x.out_port_if)
    return y.stream_out_if


outer_inst, outer_inst_t = make_hw_func_from_interface_func(outer)


@MAIN
def top_compose(s_if: chan_intrf.fwd_t, out_port_if: chan_intrf.fb_t) -> outer_inst_t:
    return outer_inst(s_if, out_port_if)


def test_composition_and_memoization():
    a1, _ = make_hw_func_from_interface_func(inner)
    a2, _ = make_hw_func_from_interface_func(inner)
    assert a1 is a2, "one definition, many instances"
    sim_reset()
    r = sim_call(top_compose, chan_intrf.fwd_t(data=1, valid=1), chan_intrf.fb_t(ready=1))
    assert int(r.out_port_if.data) == 8 and int(r.s_if.ready) == 1


# ── rejections ──
def _expect(fn, needle):
    try:
        fn()
    except InterfaceError as e:
        assert needle in str(e), f"wrong message: {e}"
        return
    raise AssertionError(f"expected InterfaceError containing {needle!r}")


def test_rejections():
    def fan_out(a: chan_intrf) -> pair:
        p = inc2(a)
        q = inc2(p.stream_out_if)
        r = inc5(p.stream_out_if)
        return pair(x=q.stream_out_if, y=r.stream_out_if)

    def dangling(s: chan_intrf) -> chan_intrf:
        f = fork_mod(s)
        return f.a_if

    def control_flow(a: chan_intrf) -> chan_intrf:
        if a.valid:
            pass
        p = inc2(a)
        return p.stream_out_if

    def ternary(a: chan_intrf) -> chan_intrf:
        p = inc2(a if a.valid else a)
        return p.stream_out_if

    def bypass(a: chan_intrf) -> chan_intrf:
        return a

    def iface_in_plain_stmt(a: chan_intrf) -> chan_intrf:
        z: uint8_t = a.data + 1
        p = scale(a, z)
        return p.stream_out_if

    _expect(
        lambda: make_hw_func_from_interface_func(fan_out), "consumed more than once"
    )
    _expect(lambda: make_hw_func_from_interface_func(dangling), "never consumed")
    _expect(
        lambda: make_hw_func_from_interface_func(control_flow),
        "control flow is not allowed",
    )
    _expect(
        lambda: make_hw_func_from_interface_func(ternary), "conditional expression"
    )
    _expect(
        lambda: make_hw_func_from_interface_func(bypass), "not consumed by any call"
    )
    _expect(
        lambda: make_hw_func_from_interface_func(iface_in_plain_stmt),
        "outside of a module call",
    )


# a two-output element used only by the `dangling` rejection above
@struct
class fork_t(NamedTuple):
    stream_in_if: chan_intrf.fb_t
    a_if: chan_intrf.fwd_t
    b_if: chan_intrf.fwd_t


@hw_func
def fork_mod(stream_in_if: chan_intrf.fwd_t, a_if: chan_intrf.fb_t, b_if: chan_intrf.fb_t) -> fork_t:
    o: fork_t
    o.a_if.data = stream_in_if.data
    o.a_if.valid = stream_in_if.valid
    o.b_if.data = stream_in_if.data
    o.b_if.valid = stream_in_if.valid
    o.stream_in_if.ready = a_if.ready & b_if.ready
    return o


# ── keyword arguments at call sites ──
# Same wiring as the positional `series`/`with_plain` above, written with
# keywords. Callee param names are arbitrary (structural pairing), so a keyword
# binds by the callee's declared name; the reverse halves of output ports are
# synthesized and must not be named.
def series_kw(stream_in_if: chan_intrf) -> chan_intrf:
    a = inc2(stream_in_if=stream_in_if)  # all-keyword
    b = inc5(stream_in_if=a.stream_out_if)
    return b.stream_out_if


series_kw_inst, series_kw_inst_t = make_hw_func_from_interface_func(series_kw)


@MAIN
def top_sugar_kw(stream_in_if: chan_intrf.fwd_t, out_port_if: chan_intrf.fb_t) -> series_kw_inst_t:
    return series_kw_inst(stream_in_if, out_port_if)


def with_mixed(a_if: chan_intrf, k: uint8_t) -> chan_intrf:
    kk: uint8_t = k + 1
    m = scale(a_if, k=kk)  # mixed: positional interface arg, keyword plain arg
    return m.stream_out_if


mixed_inst, mixed_inst_t = make_hw_func_from_interface_func(with_mixed)


@MAIN
def top_mixed(a_if: chan_intrf.fwd_t, k: uint8_t, out_port_if: chan_intrf.fb_t) -> mixed_inst_t:
    return mixed_inst(a_if, k, out_port_if)


def test_all_keyword_matches_positional_twin():
    """An all-keyword call site wires identically to the hand-written twin the
    positional `series` was checked against."""
    sim_reset()
    for data, valid, rdy in [(10, 1, 1), (0, 0, 1), (200, 1, 0), (7, 1, 1)]:
        kw = sim_call(top_sugar_kw, chan_intrf.fwd_t(data=data, valid=valid), chan_intrf.fb_t(ready=rdy))
        tw = sim_call(top_twin, chan_intrf.fwd_t(data=data, valid=valid), chan_intrf.fb_t(ready=rdy))
        assert int(kw.out_port_if.data) == int(tw.out_port_if.data) == (data + 7) & 0xFF
        assert int(kw.out_port_if.valid) == int(tw.out_port_if.valid) == valid
        assert int(kw.stream_in_if.ready) == int(tw.stream_in_if.ready) == rdy


def test_mixed_positional_and_keyword():
    sim_reset()
    r = sim_call(top_mixed, chan_intrf.fwd_t(data=10, valid=1), 4, chan_intrf.fb_t(ready=1))
    assert int(r.out_port_if.data) == 15  # 10 + (4 + 1)
    assert int(r.a_if.ready) == 1


def test_keyword_rejections():
    def unknown_kw(s: chan_intrf) -> chan_intrf:
        a = inc2(stream_in_if=s, bogus=s)
        return a.stream_out_if

    def feedback_kw(s: chan_intrf) -> chan_intrf:
        a = inc2(stream_in_if=s, stream_out_if=s)  # naming a synthesized reverse half
        return a.stream_out_if

    def duplicate_arg(s: chan_intrf) -> chan_intrf:
        a = inc2(s, stream_in_if=s)  # positional + keyword for the same param
        return a.stream_out_if

    def missing_arg(a: chan_intrf, k: uint8_t) -> chan_intrf:
        kk: uint8_t = k + 1
        m = scale(k=kk)  # stream_in_if never supplied
        return m.stream_out_if

    def too_many_positional(s: chan_intrf) -> chan_intrf:
        a = inc2(s, s, s)
        return a.stream_out_if

    _expect(
        lambda: make_hw_func_from_interface_func(unknown_kw),
        "unexpected keyword argument",
    )
    _expect(
        lambda: make_hw_func_from_interface_func(feedback_kw), "reverse (feedback) port"
    )
    _expect(
        lambda: make_hw_func_from_interface_func(duplicate_arg),
        "multiple values for argument",
    )
    _expect(
        lambda: make_hw_func_from_interface_func(missing_arg),
        "missing feedforward argument",
    )
    _expect(
        lambda: make_hw_func_from_interface_func(too_many_positional),
        "positional feedforward args but the module takes",
    )


if __name__ == "__main__":
    test_ports_introspected_structurally()
    test_chain_matches_hand_written_twin()
    test_multi_in_out_bundle()
    test_multi_field_non_bit_reverse()
    test_plain_values_pass_through()
    test_composition_and_memoization()
    test_rejections()
    test_all_keyword_matches_positional_twin()
    test_mixed_positional_and_keyword()
    test_keyword_rejections()
    print("OK: interface functions (chain, bundles, plain, compose, keywords, rejections)")
