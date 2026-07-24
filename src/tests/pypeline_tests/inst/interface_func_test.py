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
from interface.interface import (
    interface,
    make_interface_type,
    make_interface_feedback_type,
)
from interface.interface_func import (
    InterfaceError,
    callee_ports,
    make_hw_func_from_interface_func,
)


@interface
class chan(NamedTuple):
    data: uint8_t
    valid: uint1_t
    ready: Feedback[uint1_t]


chan_t = make_interface_type(chan)
chan_fb_t = make_interface_feedback_type(chan)


def make_inc(k):
    """A combinational element declared with the interface's split structs."""

    @struct
    class inc_t(NamedTuple):
        stream_in: chan_fb_t  # input port's reverse half travels out
        stream_out: chan_t  # output port's feedforward half travels out

    @hw_func
    def inc(stream_in: chan_t, stream_out: chan_fb_t) -> inc_t:
        o: inc_t
        o.stream_out.data = stream_in.data + k
        o.stream_out.valid = stream_in.valid
        o.stream_in.ready = stream_out.ready
        return o

    return inc, inc_t


inc2, inc2_t = make_inc(2)
inc5, inc5_t = make_inc(5)


def test_ports_introspected_structurally():
    """Direction comes from which side holds the feedforward half -- no name
    convention is consulted, so port names are arbitrary."""
    ports, _params, _ret = callee_ports(inc2)
    assert {n: p.direction for n, p in ports.items()} == {
        "stream_in": "in",
        "stream_out": "out",
    }


# ── two-stage chain: sugar vs hand-written explicit twin ──
def series(stream_in: chan) -> chan:
    a = inc2(stream_in)
    b = inc5(a.stream_out)
    return b.stream_out


series_inst, series_inst_t = make_hw_func_from_interface_func(series)


@MAIN
def top_sugar(stream_in: chan_t, out_port: chan_fb_t) -> series_inst_t:
    return series_inst(stream_in, out_port)


@hw_func
def series_twin(stream_in: chan_t, out_port: chan_fb_t) -> inc5_t:
    rev: Feedback[chan_fb_t]
    a = inc2(stream_in, rev)
    b = inc5(a.stream_out, out_port)
    rev = b.stream_in
    o: inc5_t
    o.stream_out = b.stream_out
    o.stream_in = a.stream_in
    return o


@MAIN
def top_twin(stream_in: chan_t, out_port: chan_fb_t) -> inc5_t:
    return series_twin(stream_in, out_port)


def test_chain_matches_hand_written_twin():
    sim_reset()
    for data, valid, rdy in [(10, 1, 1), (0, 0, 1), (200, 1, 0), (7, 1, 1)]:
        s = sim_call(top_sugar, chan_t(data=data, valid=valid), chan_fb_t(ready=rdy))
        t = sim_call(top_twin, chan_t(data=data, valid=valid), chan_fb_t(ready=rdy))
        assert int(s.out_port.data) == int(t.stream_out.data) == (data + 7) & 0xFF
        assert int(s.out_port.valid) == int(t.stream_out.valid) == valid
        assert int(s.stream_in.ready) == int(t.stream_in.ready) == rdy


# ── multiple in/out via an interface bundle ──
@interface
class pair(NamedTuple):
    x: chan
    y: chan


def two_lanes(a: chan, b: chan) -> pair:
    p = inc2(a)
    q = inc5(b)
    return pair(x=p.stream_out, y=q.stream_out)


lanes_inst, lanes_inst_t = make_hw_func_from_interface_func(two_lanes)


@MAIN
def top_lanes(a: chan_t, b: chan_t, x: chan_fb_t, y: chan_fb_t) -> lanes_inst_t:
    return lanes_inst(a, b, x, y)


def test_multi_in_out_bundle():
    sim_reset()
    r = sim_call(
        top_lanes,
        chan_t(data=10, valid=1),
        chan_t(data=20, valid=0),
        chan_fb_t(ready=1),
        chan_fb_t(ready=0),
    )
    assert int(r.x.data) == 12 and int(r.x.valid) == 1
    assert int(r.y.data) == 25 and int(r.y.valid) == 0
    # each lane's reverse half is routed back independently
    assert int(r.a.ready) == 1 and int(r.b.ready) == 0


# ── a non-uint1_t reverse channel, and >1 reverse field ──
@interface
class credit_chan(NamedTuple):
    data: uint8_t
    valid: uint1_t
    credit: Feedback[uint2_t]
    halt: Feedback[uint1_t]


cc_t = make_interface_type(credit_chan)
cc_fb_t = make_interface_feedback_type(credit_chan)


@struct
class cpass_t(NamedTuple):
    stream_in: cc_fb_t
    stream_out: cc_t


@hw_func
def cpass(stream_in: cc_t, stream_out: cc_fb_t) -> cpass_t:
    o: cpass_t
    o.stream_out.data = stream_in.data + 1
    o.stream_out.valid = stream_in.valid
    o.stream_in.credit = stream_out.credit
    o.stream_in.halt = stream_out.halt
    return o


def credit_series(s: credit_chan) -> credit_chan:
    a = cpass(s)
    b = cpass(a.stream_out)
    return b.stream_out


cs_inst, cs_inst_t = make_hw_func_from_interface_func(credit_series)


@MAIN
def top_credit(s: cc_t, out_port: cc_fb_t) -> cs_inst_t:
    return cs_inst(s, out_port)


def test_multi_field_non_bit_reverse():
    sim_reset()
    r = sim_call(top_credit, cc_t(data=5, valid=1), cc_fb_t(credit=2, halt=1))
    assert int(r.out_port.data) == 7
    # the whole multi-field reverse bundle is threaded back, not just one bit
    assert int(r.s.credit) == 2 and int(r.s.halt) == 1


# ── plain (non-interface) values: params, and a plain intermediate statement ──
@struct
class scale_t(NamedTuple):
    stream_in: chan_fb_t
    stream_out: chan_t


@hw_func
def scale(stream_in: chan_t, k: uint8_t, stream_out: chan_fb_t) -> scale_t:
    o: scale_t
    o.stream_out.data = stream_in.data + k
    o.stream_out.valid = stream_in.valid
    o.stream_in.ready = stream_out.ready
    return o


def with_plain(a: chan, k: uint8_t) -> chan:
    kk: uint8_t = k + 1  # plain statement: copied through verbatim
    m = scale(a, kk)
    return m.stream_out


plain_inst, plain_inst_t = make_hw_func_from_interface_func(with_plain)


@MAIN
def top_plain(a: chan_t, k: uint8_t, out_port: chan_fb_t) -> plain_inst_t:
    return plain_inst(a, k, out_port)


def test_plain_values_pass_through():
    # a non-interface param rides through with no reverse companion
    assert "k" not in plain_inst_t._fields
    sim_reset()
    r = sim_call(top_plain, chan_t(data=10, valid=1), 4, chan_fb_t(ready=1))
    assert int(r.out_port.data) == 15  # 10 + (4+1)
    assert int(r.a.ready) == 1


# ── composition: an interface function calling another ──
def inner(s: chan) -> chan:
    a = inc2(s)
    return a.stream_out


def outer(s: chan) -> chan:
    x = inner(s)
    y = inc5(x.out_port)
    return y.stream_out


outer_inst, outer_inst_t = make_hw_func_from_interface_func(outer)


@MAIN
def top_compose(s: chan_t, out_port: chan_fb_t) -> outer_inst_t:
    return outer_inst(s, out_port)


def test_composition_and_memoization():
    a1, _ = make_hw_func_from_interface_func(inner)
    a2, _ = make_hw_func_from_interface_func(inner)
    assert a1 is a2, "one definition, many instances"
    sim_reset()
    r = sim_call(top_compose, chan_t(data=1, valid=1), chan_fb_t(ready=1))
    assert int(r.out_port.data) == 8 and int(r.s.ready) == 1


# ── rejections ──
def _expect(fn, needle):
    try:
        fn()
    except InterfaceError as e:
        assert needle in str(e), f"wrong message: {e}"
        return
    raise AssertionError(f"expected InterfaceError containing {needle!r}")


def test_rejections():
    def fan_out(a: chan) -> pair:
        p = inc2(a)
        q = inc2(p.stream_out)
        r = inc5(p.stream_out)
        return pair(x=q.stream_out, y=r.stream_out)

    def dangling(s: chan) -> chan:
        f = fork_mod(s)
        return f.a

    def control_flow(a: chan) -> chan:
        if a.valid:
            pass
        p = inc2(a)
        return p.stream_out

    def ternary(a: chan) -> chan:
        p = inc2(a if a.valid else a)
        return p.stream_out

    def bypass(a: chan) -> chan:
        return a

    def iface_in_plain_stmt(a: chan) -> chan:
        z: uint8_t = a.data + 1
        p = scale(a, z)
        return p.stream_out

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
    stream_in: chan_fb_t
    a: chan_t
    b: chan_t


@hw_func
def fork_mod(stream_in: chan_t, a: chan_fb_t, b: chan_fb_t) -> fork_t:
    o: fork_t
    o.a.data = stream_in.data
    o.a.valid = stream_in.valid
    o.b.data = stream_in.data
    o.b.valid = stream_in.valid
    o.stream_in.ready = a.ready & b.ready
    return o


# ── keyword arguments at call sites ──
# Same wiring as the positional `series`/`with_plain` above, written with
# keywords. Callee param names are arbitrary (structural pairing), so a keyword
# binds by the callee's declared name; the reverse halves of output ports are
# synthesized and must not be named.
def series_kw(stream_in: chan) -> chan:
    a = inc2(stream_in=stream_in)  # all-keyword
    b = inc5(stream_in=a.stream_out)
    return b.stream_out


series_kw_inst, series_kw_inst_t = make_hw_func_from_interface_func(series_kw)


@MAIN
def top_sugar_kw(stream_in: chan_t, out_port: chan_fb_t) -> series_kw_inst_t:
    return series_kw_inst(stream_in, out_port)


def with_mixed(a: chan, k: uint8_t) -> chan:
    kk: uint8_t = k + 1
    m = scale(a, k=kk)  # mixed: positional interface arg, keyword plain arg
    return m.stream_out


mixed_inst, mixed_inst_t = make_hw_func_from_interface_func(with_mixed)


@MAIN
def top_mixed(a: chan_t, k: uint8_t, out_port: chan_fb_t) -> mixed_inst_t:
    return mixed_inst(a, k, out_port)


def test_all_keyword_matches_positional_twin():
    """An all-keyword call site wires identically to the hand-written twin the
    positional `series` was checked against."""
    sim_reset()
    for data, valid, rdy in [(10, 1, 1), (0, 0, 1), (200, 1, 0), (7, 1, 1)]:
        kw = sim_call(top_sugar_kw, chan_t(data=data, valid=valid), chan_fb_t(ready=rdy))
        tw = sim_call(top_twin, chan_t(data=data, valid=valid), chan_fb_t(ready=rdy))
        assert int(kw.out_port.data) == int(tw.stream_out.data) == (data + 7) & 0xFF
        assert int(kw.out_port.valid) == int(tw.stream_out.valid) == valid
        assert int(kw.stream_in.ready) == int(tw.stream_in.ready) == rdy


def test_mixed_positional_and_keyword():
    sim_reset()
    r = sim_call(top_mixed, chan_t(data=10, valid=1), 4, chan_fb_t(ready=1))
    assert int(r.out_port.data) == 15  # 10 + (4 + 1)
    assert int(r.a.ready) == 1


def test_keyword_rejections():
    def unknown_kw(s: chan) -> chan:
        a = inc2(stream_in=s, bogus=s)
        return a.stream_out

    def feedback_kw(s: chan) -> chan:
        a = inc2(stream_in=s, stream_out=s)  # naming a synthesized reverse half
        return a.stream_out

    def duplicate_arg(s: chan) -> chan:
        a = inc2(s, stream_in=s)  # positional + keyword for the same param
        return a.stream_out

    def missing_arg(a: chan, k: uint8_t) -> chan:
        kk: uint8_t = k + 1
        m = scale(k=kk)  # stream_in never supplied
        return m.stream_out

    def too_many_positional(s: chan) -> chan:
        a = inc2(s, s, s)
        return a.stream_out

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
