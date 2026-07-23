# pyright: reportInvalidTypeForm=none
"""Definition-site warning for a half-declared interface port.

A port's two halves share the port's name -- the feedforward half on one side of
a hw_func's signature (an argument or a return field), the reverse half on the
other. Declaring one without the other is usually an unfinished port, so
`@hw_func` warns at decoration time (`InterfacePortWarning`). This is a warning,
not an error: the exact same shape is a legitimate *valid-only* stream (data +
valid with no backpressure), which the message calls out and which the standard
warnings filter can silence. The hard error stays where interfaces are actually
composed (an interface function instantiating such a module -- see
`interface_mixing_rules_test.py`).
"""
import sys, os
import warnings

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
    InterfacePortWarning,
)
from interface.interface import (
    interface,
    make_interface_type,
    make_interface_feedback_type,
)


@interface
class chan(NamedTuple):
    data: uint8_t
    valid: uint1_t
    ready: Feedback[uint1_t]


chan_t = make_interface_type(chan)
chan_fb_t = make_interface_feedback_type(chan)


# a one-directional (feedforward-only) interface: a single half IS complete
@interface
class oneway(NamedTuple):
    data: uint8_t
    valid: uint1_t


oneway_t = make_interface_type(oneway)
assert make_interface_feedback_type(oneway) is None  # no reverse half exists


def _iface_warnings(build):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        build()
    return [w for w in caught if issubclass(w.category, InterfacePortWarning)]


def test_lone_feedforward_half_warns():
    """An input port's feedforward half in the args, but no reverse half in the
    return -- the exact 'forgot the other half' shape. (The plain `uint8_t`
    output is not an interface, so `stream_in` is the only port here.)"""

    def build():
        @hw_func
        def m(stream_in: chan_t) -> uint8_t:  # no `stream_in` fb returned
            return stream_in.data

    ws = _iface_warnings(build)
    assert len(ws) == 1
    msg = str(ws[0].message)
    assert "stream_in" in msg
    assert "feedforward" in msg and "reverse" in msg  # present + missing named
    assert "return field" in msg  # the missing half's side is pointed out
    assert "valid-only" in msg  # the escape hatch is named


def test_each_lone_half_warns_once():
    """A function that leaves *both* an input and an output port half-declared
    warns once per port -- confirming the per-port granularity."""

    def build():
        @struct
        class two_lone_t(NamedTuple):
            stream_out: chan_t  # output port fwd half, no fb arg -> lone

        @hw_func
        def m(stream_in: chan_t) -> two_lone_t:  # input fwd half, no fb ret -> lone
            o: two_lone_t
            o.stream_out = stream_in
            return o

    names = {
        n
        for w in _iface_warnings(build)
        for n in ("stream_in", "stream_out")
        if n in str(w.message)
    }
    assert names == {"stream_in", "stream_out"}


def test_lone_reverse_half_warns():
    """A bare reverse half with no forward -- backpressure for a stream that
    isn't there. Almost always a real bug, so it warns too."""

    def build():
        @struct
        class lone_rev_t(NamedTuple):
            stream_out: chan_fb_t  # reverse half, but no forward half anywhere

        @hw_func
        def m(x: uint8_t) -> lone_rev_t:
            o: lone_rev_t
            o.stream_out.ready = 1
            return o

    ws = _iface_warnings(build)
    assert len(ws) == 1
    msg = str(ws[0].message)
    assert "stream_out" in msg and "reverse" in msg and "feedforward" in msg
    assert "argument" in msg  # the missing forward half belongs on the arg side


def test_complete_port_is_silent():
    """Both halves present (input port: fwd arg + fb return) -- no warning."""

    def build():
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

    assert _iface_warnings(build) == []


def test_one_directional_interface_is_silent():
    """A feedforward-only interface has no reverse half to pair, so a lone
    forward half is complete and must not warn."""

    def build():
        @hw_func
        def m(x: oneway_t) -> oneway_t:
            return x

    assert _iface_warnings(build) == []


def test_plain_signals_are_silent():
    """A hw_func with no interface types at all never warns."""

    def build():
        @hw_func
        def m(a: uint8_t, b: uint8_t) -> uint8_t:
            return a + b

    assert _iface_warnings(build) == []


def test_warning_is_suppressable_by_standard_filter():
    """Intentional valid-only code silences it the ordinary Python way."""

    def build():
        @struct
        class vonly_t(NamedTuple):
            stream_out: chan_t

        @hw_func
        def m(stream_in: chan_t) -> vonly_t:
            o: vonly_t
            o.stream_out = stream_in
            return o

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        warnings.filterwarnings("ignore", category=InterfacePortWarning)
        build()
    assert [w for w in caught if issubclass(w.category, InterfacePortWarning)] == []


if __name__ == "__main__":
    test_lone_feedforward_half_warns()
    test_lone_reverse_half_warns()
    test_complete_port_is_silent()
    test_one_directional_interface_is_silent()
    test_plain_signals_are_silent()
    test_warning_is_suppressable_by_standard_filter()
    print("OK: def-site interface-half pairing warning behaves correctly")
