# pyright: reportInvalidTypeForm=none
"""Elaboration of submodule calls whose arguments are passed by keyword.

The Layer-2 elaborator (PY_TO_LOGIC) used to bind only positional args
(`zip(expr.args, callee.inputs)`) and never looked at `expr.keywords`, so a
keyword-argument hw_func call left the matching inputs undriven and blew up much
later with a `KeyError` in duplicate-submodule collapsing
(`wire_driven_by[inst____port]`). Native sim (Layer 1, plain Python) always
handled keywords, so the gap only ever surfaced in real elaboration / VHDL
generation -- e.g. wireguard's `pipeline_func(stream_in=..., stream_out=...)`.

This design forces that path under `--no_synth`: an all-keyword call, an
all-keyword call written in reversed source order (must still bind by name, not
position), and a mixed positional+keyword call. Elaborating all three cleanly is
the regression check; the sim asserts each still computes the right value, which
would differ if an argument bound to the wrong port.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../"))

from pypeline import MAIN, hw_func, sim_call, uint8_t


# Weighted so argument order is observable: a mis-bound port changes the result.
@hw_func
def weighted_sum(a: uint8_t, b: uint8_t, c: uint8_t) -> uint8_t:
    return (a << 2) + (b << 1) + c


@MAIN
def kw_in_order(x: uint8_t, y: uint8_t, z: uint8_t) -> uint8_t:
    return weighted_sum(a=x, b=y, c=z)


@MAIN
def kw_reversed(x: uint8_t, y: uint8_t, z: uint8_t) -> uint8_t:
    # Reversed source order -- correct wiring depends on name, not position.
    return weighted_sum(c=z, a=x, b=y)


@MAIN
def kw_mixed(x: uint8_t, y: uint8_t, z: uint8_t) -> uint8_t:
    # Positional `a`, then the rest by keyword out of order.
    return weighted_sum(x, c=z, b=y)


def test_keyword_calls_sim():
    # a<<2 + b<<1 + c = 3*4 + 2*2 + 1 = 17 for every binding, iff each argument
    # reaches its intended port.
    for main in (kw_in_order, kw_reversed, kw_mixed):
        r = sim_call(main, 3, 2, 1)
        assert int(r) == 17, f"{main.__name__}: expected 17, got {int(r)}"
    print("test_keyword_calls_sim PASS")


if __name__ == "__main__":
    test_keyword_calls_sim()
