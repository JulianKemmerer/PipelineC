# pyright: reportInvalidTypeForm=none
"""Definition-site hard error for a half-declared interface port.

A port's two halves share the port's name -- the feedforward half on one side of
a hw_func's signature (an argument or a return field), the reverse half on the
other. Declaring one without the other is (almost) always an unfinished port,
so `@hw_func` raises `InterfacePortError` at decoration time.

The one legitimate lone-half shape -- an intentional valid-only / data-only
stream (data + valid, no backpressure) -- is not an exception carved out of
this check: it is built as a genuinely one-directional type
(`stream.make_stream_t(...)` / `axi.make_axis_t(...)`, whose derived feedback
half is `None`), so it is exempt by construction, the same way any other
one-directional `@interface` is. The hard error at composition time (an
interface function instantiating a module and leaving its reverse half
undriven) is a separate, pre-existing check -- see `interface_mixing_rules_test.py`.
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
    hw_func,
    struct,
    NamedTuple,
    Feedback,
    uint1_t,
    uint8_t,
    InterfacePortError,
)
from interface.interface import interface
from stream.stream import make_stream_t


@interface
class chan(NamedTuple):
    data: uint8_t
    valid: uint1_t
    ready: Feedback[uint1_t]


chan_t = chan.fwd_t
chan_fb_t = chan.fb_t


# a one-directional (feedforward-only) interface: a single half IS complete
@interface
class oneway(NamedTuple):
    data: uint8_t
    valid: uint1_t


oneway_t = oneway.fwd_t
assert oneway.fb_t is None  # no reverse half exists


def _expect_error(build):
    try:
        build()
    except InterfacePortError as e:
        return str(e)
    raise AssertionError("expected InterfacePortError, none was raised")


def test_lone_feedforward_half_errors():
    """An input port's feedforward half in the args, but no reverse half in the
    return -- the exact 'forgot the other half' shape. (The plain `uint8_t`
    output is not an interface, so `stream_in` is the only port here.)"""

    def build():
        @hw_func
        def m(stream_in: chan_t) -> uint8_t:  # no `stream_in` fb returned
            return stream_in.data

    msg = _expect_error(build)
    assert "stream_in" in msg
    assert "feedforward" in msg and "reverse" in msg  # present + missing named
    assert "return field" in msg  # the missing half's side is pointed out
    assert "make_stream_t" in msg  # the valid-only route is named


def test_lone_reverse_half_errors():
    """A bare reverse half with no forward -- backpressure for a stream that
    isn't there. Almost always a real bug, so it errors too."""

    def build():
        @struct
        class lone_rev_t(NamedTuple):
            stream_out: chan_fb_t  # reverse half, but no forward half anywhere

        @hw_func
        def m(x: uint8_t) -> lone_rev_t:
            o: lone_rev_t
            o.stream_out.ready = 1
            return o

    msg = _expect_error(build)
    assert "stream_out" in msg and "reverse" in msg and "feedforward" in msg
    assert "argument" in msg  # the missing forward half belongs on the arg side


def test_first_lone_half_errors():
    """A function that leaves *both* an input and an output port half-declared
    raises on the first one found -- confirming the check runs, not that both
    are enumerated (a hard error stops at the first problem)."""

    def build():
        @struct
        class two_lone_t(NamedTuple):
            stream_out: chan_t  # output port fwd half, no fb arg -> lone

        @hw_func
        def m(stream_in: chan_t) -> two_lone_t:  # input fwd half, no fb ret -> lone
            o: two_lone_t
            o.stream_out = stream_in
            return o

    msg = _expect_error(build)
    assert "stream_in" in msg or "stream_out" in msg


def test_complete_port_is_silent():
    """Both halves present (input port: fwd arg + fb return) -- no error."""

    @struct
    class ok_t(NamedTuple):
        stream_in: chan_fb_t
        stream_out: chan_t

    @hw_func
    def m(stream_in: chan_t, stream_out: chan_fb_t) -> ok_t:
        o: ok_t
        o.stream_out = stream_in
        o.stream_in.ready = stream_out.ready
        return o


def test_one_directional_interface_is_silent():
    """A feedforward-only interface has no reverse half to pair, so a lone
    forward half is complete and must not error."""

    @hw_func
    def m(x: oneway_t) -> oneway_t:
        return x


def test_plain_signals_are_silent():
    """A hw_func with no interface types at all never errors."""

    @hw_func
    def m(a: uint8_t, b: uint8_t) -> uint8_t:
        return a + b


def test_valid_only_stream_is_silent():
    """The structural escape hatch: a lone port typed as a genuinely
    one-directional valid-only stream (`make_stream_t`, no reverse half at
    all) never errors, in place of the old suppressible warning."""

    plain_t = make_stream_t(uint8_t)

    @struct
    class vonly_t(NamedTuple):
        stream_out: plain_t

    @hw_func
    def m(stream_in: plain_t) -> vonly_t:
        o: vonly_t
        o.stream_out = stream_in
        return o


if __name__ == "__main__":
    test_lone_feedforward_half_errors()
    test_lone_reverse_half_errors()
    test_first_lone_half_errors()
    test_complete_port_is_silent()
    test_one_directional_interface_is_silent()
    test_plain_signals_are_silent()
    test_valid_only_stream_is_silent()
    print("OK: def-site interface-half pairing hard error behaves correctly")
