"""Unit checks of the reset API in pypeline.py, with no design build:

- make_reset: the supported kind and active level, and NotImplementedError
  naming the limitation for any other;
- the Reg[T, ...] markers RESET and NO_RESET: in any order with a
  MULTI_CYCLE role, and TypeError for both markers or an unknown one;
- make_clock(reset=): the read-only clk.reset, reset outside the clock's
  identity, a non-reset argument, and _clock_conflict for two primary
  resets of one clock;
- MAIN(reset=, reset_registers=) argument checks, and the reset rules both
  elaboration and native sim use (_resolve_main_reset,
  _global_inst_main_reset);
- _sanitize_vhdl_name renaming `reset`, which VHDL reads as the RESET port.
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

import pypeline
from pypeline import (
    MAIN,
    MULTI_CYCLE,
    NO_RESET,
    RESET,
    Reg,
    make_clock,
    make_reset,
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


def test_make_reset_styles():
    r = make_reset()
    assert (r.kind, r.active) == ("sync", "high")
    assert "reset_api_unit_test.py" in r.origin
    _expect(NotImplementedError, lambda: make_reset(kind="async"), "only synchronous")
    _expect(NotImplementedError, lambda: make_reset(active="low"), "only active-high")
    print("test_make_reset_styles PASS")


def test_reg_markers():
    assert Reg[uint8_t].reset_mode is None
    assert Reg[uint8_t, RESET].reset_mode == "reset"
    assert Reg[uint8_t, NO_RESET].reset_mode == "no_reset"
    mc = MULTI_CYCLE[4]
    both = Reg[uint8_t, RESET, mc.start]
    assert both.reset_mode == "reset" and both.multi_cycle_role is mc.start
    either = Reg[uint8_t, mc.end, NO_RESET]
    assert either.reset_mode == "no_reset" and either.multi_cycle_role is mc.end
    assert Reg[uint8_t, mc.start].reset_mode is None
    _expect(TypeError, lambda: Reg[uint8_t, RESET, NO_RESET], "RESET or NO_RESET, once")
    _expect(TypeError, lambda: Reg[uint8_t, RESET, RESET], "once")
    _expect(TypeError, lambda: Reg[uint8_t, 3], "markers")
    _expect(TypeError, lambda: Reg[uint8_t, mc.start, mc.end], "one MULTI_CYCLE")
    print("test_reg_markers PASS")


def test_clock_reset():
    rst = make_reset()
    clk = make_clock(100.0, reset=rst)
    assert clk.reset is rst
    assert make_clock(100.0).reset is None
    # Not part of the identity: one clock, with or without its reset named
    assert clk == make_clock(100.0) and clk.identity == (100.0, None)
    _expect(AttributeError, lambda: setattr(clk, "reset", None))
    _expect(TypeError, lambda: make_clock(100.0, reset=1), "make_reset()")
    other = make_reset()
    conflict = pypeline._clock_conflict([clk, make_clock(100.0, reset=other)])
    assert conflict is not None and "two primary resets" in conflict, conflict
    assert pypeline._clock_conflict([clk, make_clock(100.0, reset=rst), make_clock(100.0)]) is None
    assert pypeline._clock_conflict([clk, make_clock(50.0, reset=other)]) is None
    print("test_clock_reset PASS")


def test_main_reset_args():
    rst = make_reset()
    _expect(TypeError, lambda: MAIN(reset=1), "make_reset()")
    _expect(ValueError, lambda: MAIN(reset_registers="some"), '"requested"', '"all"')
    _expect(ValueError, lambda: MAIN(reset=rst, reset_registers=None), "reset_registers")
    print("test_main_reset_args PASS")


def test_resolve_main_reset():
    rst, other = make_reset(), make_reset()
    clk = make_clock(100.0, reset=rst)
    primaries = pypeline._clock_primary_resets([clk, make_clock(50.0)])
    assert primaries == {(100.0, None): rst}

    def info(**kw):
        return pypeline._MainInfo("m", False, clk, "x.py:1", **kw)

    resolve = pypeline._resolve_main_reset
    # Default: the clock's primary reset, under "requested"
    assert resolve(info(), clk.identity, primaries) == (rst, "requested")
    # A bare MAIN takes the reset of the clock it is assigned
    assert resolve(info(), (100.0, None), primaries) == (rst, "requested")
    assert resolve(info(), (50.0, None), primaries) == (None, "requested")
    assert resolve(info(reset_registers="all"), clk.identity, primaries) == (rst, "all")
    assert resolve(info(reset=other), clk.identity, primaries) == (other, "requested")
    assert resolve(info(reset=None, reset_registers="all"), clk.identity, primaries) == (None, "all")
    # A global instance's MAIN: its clock's reset, every register
    gi = pypeline._global_inst_main_reset
    assert gi((100.0, None), primaries) == (rst, "all")
    assert gi((50.0, None), primaries) == (None, "all")
    print("test_resolve_main_reset PASS")


def test_reset_name_renamed():
    assert pypeline._sanitize_vhdl_name("reset") == "reset_v"
    assert pypeline._sanitize_vhdl_name("RESET") == "RESET_v"
    assert pypeline._sanitize_vhdl_name("reset_n") == "reset_n"
    assert pypeline._sanitize_vhdl_name("rst") == "rst"
    print("test_reset_name_renamed PASS")


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
