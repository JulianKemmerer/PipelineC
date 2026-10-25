"""Unit checks of the clock API in pypeline.py, with no design build:

- make_clock: identity (rate, then name) for equality and hashing, port
  names, and argument errors; its port names agree with the back end's
  VHDL.CLK_MHZ_GROUP_TEXT for rates above and below 1 MHz;
- pypeline._clock_conflict: two syn_mhz values for one clock, and two names
  that differ only in case;
- MAIN's clock forms (@MAIN(clk), clock=, a rate, mhz=) and naming the clock
  twice;
- the ASYNC, VOLATILE and clock markers on Wire/Input/Output, and on
  Inst/Fifo, which take none;
- global_async_fifo and impl= arguments.
"""

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
import VHDL
from pypeline import (
    ASYNC,
    MAIN,
    VOLATILE,
    Fifo,
    Input,
    Output,
    Wire,
    global_async_fifo,
    global_fifo,
    global_sync_fifo,
    hw_func,
    make_clock,
    uint1_t,
    uint8_t,
)


def _expect(exc_type, fn, *tokens):
    try:
        fn()
    except exc_type as e:
        for token in tokens:
            assert token in str(e), (token, str(e))
        return
    raise AssertionError(f"expected {exc_type.__name__} mentioning {tokens}")


def test_identity_and_port_names():
    a = make_clock(25.0, name="eth_rx")
    assert a == make_clock(25, name="eth_rx") and hash(a) == hash(make_clock(25.0, name="eth_rx"))
    assert a != make_clock(25.0, name="eth_tx") and a != make_clock(25.0)
    assert make_clock(100.0) == make_clock(100.0, syn_mhz=120.0)  # syn_mhz is no identity
    assert a.port_name == "clk_25p0_eth_rx"
    assert make_clock(100.0).port_name == "clk_100p0"
    for mhz, name in ((100.0, None), (166.66, None), (0.5, "slow"), (0.00006, None), (1000 / 7, "x")):
        assert make_clock(mhz, name=name).port_name == "clk_" + VHDL.CLK_MHZ_GROUP_TEXT(
            float(mhz), name
        ), (mhz, name)
    assert make_clock(125.0).origin.startswith("clock_api_unit_test.py:")
    print("test_identity_and_port_names PASS")


def test_argument_errors():
    _expect(ValueError, lambda: make_clock(0), "mhz > 0")
    _expect(TypeError, lambda: make_clock("100"), "rate in MHz")
    _expect(ValueError, lambda: make_clock(100.0, name="a__b"), "single underscores")
    _expect(ValueError, lambda: make_clock(100.0, name="_a"), "single underscores")
    _expect(ValueError, lambda: make_clock(100.0, syn_mhz=-1), "syn_mhz")
    print("test_argument_errors PASS")


def test_clock_conflicts():
    a = make_clock(125.0, syn_mhz=147.0)
    b = make_clock(125.0, syn_mhz=150.0)
    assert "two syn_mhz values" in pypeline._clock_conflict([a, b])
    assert pypeline._clock_conflict([a, make_clock(125.0)]) is None
    c, d = make_clock(25.0, name="rx"), make_clock(25.0, name="RX")
    assert "differ only in case" in pypeline._clock_conflict([c, d])
    assert pypeline._clock_conflict([c, make_clock(25.0, name="tx")]) is None
    print("test_clock_conflicts PASS")


def test_main_clock_forms():
    registered = list(pypeline._main_registry)
    try:
        eth = make_clock(125.0, name="eth_rx")

        @hw_func
        def body() -> uint8_t:
            return 1

        def lane():
            @hw_func
            def f() -> uint8_t:
                return 2

            return f

        assert MAIN(eth)(lane())._pypeline_main.clock is eth
        assert MAIN(clock=eth)(lane())._pypeline_main.clock is eth
        assert MAIN(100.0)(lane())._pypeline_main.clock == make_clock(100.0)
        assert MAIN(mhz=50)(lane())._pypeline_main.clock == make_clock(50.0)
        assert MAIN(lane())._pypeline_main.clock is None
        _expect(TypeError, lambda: MAIN(eth, mhz=125.0), "names its clock twice")
        _expect(TypeError, lambda: MAIN(100.0, clock=eth), "names its clock twice")
        _expect(TypeError, lambda: MAIN(clock=125.0), "clock= takes a clock")
        _expect(TypeError, lambda: MAIN("fast"), "give a rate in MHz")
    finally:
        pypeline._main_registry[:] = registered
    print("test_main_clock_forms PASS")


def test_markers():
    eth = make_clock(125.0, name="eth_rx")
    w = Wire[uint8_t, ASYNC]
    assert w.is_async and w.volatile and w.clock is None, vars(w)
    assert str(w) == "Wire[uint8_t, ASYNC]"
    i = Input[uint8_t, eth]
    assert i.clock is eth and not i.is_async and not i.volatile
    o = Output[uint8_t, VOLATILE, eth]
    assert o.clock is eth and o.volatile and not o.is_async
    assert str(o) == "Output[uint8_t, clk_125p0_eth_rx, VOLATILE]"
    _expect(TypeError, lambda: Wire[uint8_t, ASYNC, VOLATILE], "ASYNC already behaves as VOLATILE")
    _expect(TypeError, lambda: Wire[uint8_t, ASYNC, eth], "use one of them")
    _expect(TypeError, lambda: Input[uint8_t, eth, eth], "optional markers")
    _expect(TypeError, lambda: Wire[uint8_t, 3], "optional markers")
    _expect(TypeError, lambda: Fifo[uint8_t, ASYNC], "takes one data type")
    _expect(pypeline.GlobalInstError, lambda: pypeline.Inst[hw_func(lambda: 1), ASYNC], "one hardware function")
    print("test_markers PASS")


def test_fifo_initializers():
    assert global_async_fifo(64).kind == "global_async_fifo"
    assert global_fifo(8, impl="builtin").impl == "builtin"
    assert global_async_fifo(8).impl is None
    _expect(ValueError, lambda: global_fifo(8, impl="xpm"), "impl is None")
    _expect(TypeError, lambda: global_sync_fifo(8, impl="builtin"), "impl")
    _expect(ValueError, lambda: global_async_fifo(0), "at least 1")
    assert repr(global_async_fifo(4, impl="builtin")) == "global_async_fifo(4, impl='builtin')"
    print("test_fifo_initializers PASS")


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
