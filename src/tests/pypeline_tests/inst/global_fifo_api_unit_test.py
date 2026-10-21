"""Unit checks of pypeline.py's global FIFO API, with no design build:
Fifo[T] and its wire type, the global_fifo(n) / global_sync_fifo(n)
initializers and the depth they build, the stream-module port helper that
native sim and the compiler share, and the FIFO MAIN generator's names.
"""

import inspect
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "include", "pypeline"
    ),
)

import pypeline
from pypeline import (
    VOLATILE,
    Fifo,
    NamedTuple,
    global_fifo,
    global_sync_fifo,
    hw_func,
    struct,
    uint1_t,
    uint8_t,
    uint16_t,
)
from stream.skid_buffer import make_skid_buffer
from stream.stream import make_stream_interface, make_stream_t
from stream.stream_fifo import make_stream_fifo


def _raises(exc_type, fn, *must_contain):
    try:
        fn()
    except exc_type as e:
        for token in must_contain:
            assert token in str(e), f"expected {token!r} in: {e}"
        return str(e)
    raise AssertionError(f"expected {exc_type.__name__}")


def test_fifo_type():
    ann = Fifo[uint8_t]
    assert str(ann) == "Fifo[uint8_t]"
    assert isinstance(ann, pypeline._WireType) and not ann.volatile
    wire_t = ann.inner_ctype
    assert wire_t._fields == ("wr", "rd")
    end_t = wire_t.__annotations__["wr"]
    assert end_t is wire_t.__annotations__["rd"]
    assert end_t._fields == ("stream", "ready")
    assert end_t.__annotations__["ready"] is uint1_t
    stream_t = end_t.__annotations__["stream"]
    assert stream_t._pypeline_ctype_name == make_stream_t(uint8_t)._pypeline_ctype_name
    assert Fifo[uint8_t].inner_ctype is wire_t, "types are built once per T"

    @struct
    class pair_t(NamedTuple):
        a: uint8_t
        b: uint16_t

    assert Fifo[pair_t].inner_ctype is not wire_t
    assert str(Fifo[uint8_t[4]]) == "Fifo[uint8_t[4]]"
    print("Fifo[T] type PASS")


def test_fifo_type_errors():
    _raises(TypeError, lambda: Fifo[uint8_t, VOLATILE], "Fifo[T]", "one data type")
    _raises(TypeError, lambda: Fifo[uint8_t, uint8_t], "one data type")
    intrf = make_stream_interface(uint8_t)
    for t in (intrf, intrf.fwd_t, intrf.fb_t):
        _raises(TypeError, lambda: Fifo[t], "not the interface or port half", "valid and ready")
    _raises(TypeError, lambda: Fifo[int], "hardware type")
    print("Fifo[T] errors PASS")


def test_initializers():
    assert (global_fifo(16).kind, global_fifo(16).n) == ("global_fifo", 16)
    assert global_sync_fifo(3).kind == "global_sync_fifo"
    for kind in (global_fifo, global_sync_fifo):
        _raises(ValueError, lambda: kind(0), "at least 1")
        _raises(ValueError, lambda: kind(-4), "at least 1")
        for bad in (2.0, "4", None, True):
            _raises(TypeError, lambda: kind(bad), "an int")
    # n words at least, rounded up to a power of two, at least 2
    for n, depth in ((1, 2), (2, 2), (3, 4), (4, 4), (5, 8), (64, 64), (65, 128)):
        hw = pypeline._global_fifo_hardware(uint8_t, global_fifo(n))
        assert hw.depth == depth, (n, hw.depth)
    module = make_stream_fifo(uint8_t, 8)
    assert pypeline._global_fifo_hardware(uint8_t, module) is module
    print("initializers PASS")


def test_port_helper():
    ports = pypeline._stream_module_ports
    in_port, out_port, in_fwd_t, out_fb_t = ports(make_stream_fifo(uint8_t, 4), uint8_t, "x")
    assert (in_port, out_port) == ("in_stream_if", "out_stream_if")
    assert in_fwd_t._pypeline_interface_role == "fwd"
    assert out_fb_t._pypeline_interface_role == "fb"
    assert ports(make_skid_buffer(uint8_t), uint8_t, "x")[:2] == (
        "stream_in_if",
        "stream_out_if",
    )
    what = "global FIFO 'rx'"
    err = pypeline.GlobalFifoError
    _raises(err, lambda: ports(make_stream_fifo(uint16_t, 4), uint8_t, what),
            what, "does not carry make_stream_t(uint8_t)")
    _raises(err, lambda: ports(42, uint8_t, what), "not a hardware function")

    @hw_func
    def not_a_stream(x: uint8_t) -> uint8_t:
        return x

    _raises(err, lambda: ports(not_a_stream, uint8_t, what), "argument 'x'", "not_a_stream")

    wide = make_stream_interface(uint8_t, feedback_t=uint8_t)

    @struct
    class wide_ret_t(NamedTuple):
        out_if: wide.fwd_t
        in_if: wide.fb_t

    @hw_func
    def wide_ready(in_if: wide.fwd_t, out_if: wide.fb_t) -> wide_ret_t:
        o: wide_ret_t
        return o

    _raises(err, lambda: ports(wide_ready, uint8_t, what), "no uint1_t ready")

    intrf = make_stream_interface(uint8_t)

    @struct
    class three_ret_t(NamedTuple):
        out_if: intrf.fwd_t
        in_if: intrf.fb_t
        aux_if: intrf.fwd_t

    @hw_func
    def three_ports(in_if: intrf.fwd_t, out_if: intrf.fb_t, aux_if: intrf.fb_t) -> three_ret_t:
        o: three_ret_t
        return o

    _raises(err, lambda: ports(three_ports, uint8_t, what), "its ports are")
    print("port helper PASS")


def test_fifo_main_generator():
    ann = Fifo[uint8_t]
    # A module whose globals use the generator's preferred names
    module_globals = {
        "__name__": "some_design",
        "__annotations__": {"rx": ann, "fifo_ports": ann},
        "rx": global_fifo(4),
        "fifo_hardware": 1,
        "fifo_in_t": 2,
    }
    main = pypeline._make_global_fifo_main(
        "rx_FIFO", "rx", ann, global_fifo(4), module_globals, reserved={"fifo_out_t"}
    )
    src = inspect.getsource(inspect.unwrap(main))
    assert src.startswith("def rx_FIFO():"), src
    for taken in ("fifo_hardware", "fifo_in_t", "fifo_out_t", "fifo_ports"):
        assert f"{taken}_2" in src, (taken, src)
        assert f" {taken}(" not in src and f" {taken} =" not in src, (taken, src)
    assert "rx.wr.ready = " in src and "rx.rd.stream = " in src, src
    assert main._pypeline_global_fifo == "rx"
    assert main.__module__ == "some_design"
    assert pypeline.is_hw_func(main)
    print("FIFO MAIN generator PASS")


if __name__ == "__main__":
    test_fifo_type()
    test_fifo_type_errors()
    test_initializers()
    test_port_helper()
    test_fifo_main_generator()
    print("global_fifo_api_unit_test: all PASS")
