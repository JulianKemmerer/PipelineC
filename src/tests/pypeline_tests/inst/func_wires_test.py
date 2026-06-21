# pyright: reportInvalidTypeForm=none
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

from typing import NamedTuple

from pypeline import (
    MAIN,
    sim_call,
    struct,
    uint8_t,
    wires,
)


@struct
class pair_t(NamedTuple):
    a: uint8_t
    b: uint8_t


# Plain helper, just rewiring a struct into a byte array — equivalent to PipelineC's
# `#pragma FUNC_WIRES pair_to_bytes`.
@wires
def pair_to_bytes(p: pair_t) -> uint8_t[2]:
    return [p.a, p.b]


# Mirrors include/leds/leds_port.c, which independently tags its `#pragma MAIN`
# function with `#pragma FUNC_WIRES` too — @wires stacks with @MAIN.
@MAIN
@wires
def func_wires_main(p: pair_t) -> uint8_t[2]:
    return pair_to_bytes(p)


def test_wires_sim_call():
    """@wires implies @hw_func: callable directly via sim_call(), no extra decorator."""
    result = sim_call(pair_to_bytes, pair_t(a=1, b=2))
    result_ints = [int(v) for v in result]
    assert result_ints == [1, 2], f"expected [1, 2], got {result_ints}"
    print(f"test_wires_sim_call PASS  result={result_ints}")


def test_wires_main_sim_call():
    result = sim_call(func_wires_main, pair_t(a=3, b=4))
    result_ints = [int(v) for v in result]
    assert result_ints == [3, 4], f"expected [3, 4], got {result_ints}"
    print(f"test_wires_main_sim_call PASS  result={result_ints}")


if __name__ == "__main__":
    test_wires_sim_call()
    test_wires_main_sim_call()
