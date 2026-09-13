# pyright: reportInvalidTypeForm=none
"""AUTOPIPELINE(func, latency=N) in plain native simulation.

A fixed latency is a functional contract, so -- unlike an unconstrained
AUTOPIPELINE, which is a zero-latency passthrough until a build installs its
discovered stage count -- it is emulated even in plain native sim: .latency
reads N at import time and the call site delays func's output by N cycles
(typed zeros during warm-up). start_latency= / max_latency= only steer a
synthesizing build's sweep, so they read 0 and add no delay here.

Runs two ways (both registered): as a plain script (sim_call cycle checks
below) and as a @MAIN self-check through pypeline_sim / `pypelinec --sim
--comb`, which pipeline_latency_test.py also uses to prove that plain native
sim of a fixed latency never imports the compiler.
"""
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

from pypeline import (
    AUTOPIPELINE,
    MAIN,
    Reg,
    hw_func,
    sim_assert,
    sim_call,
    sim_finish,
    sim_reset,
    uint16_t,
)


@hw_func
def plus_seven(x: uint16_t) -> uint16_t:
    return x + 7


FIXED3 = AUTOPIPELINE(plus_seven, latency=3)
FIXED0 = AUTOPIPELINE(plus_seven, latency=0)
STARTED = AUTOPIPELINE(plus_seven, start_latency=2, max_latency=4)
CAPPED = AUTOPIPELINE(plus_seven, max_latency=1)

# Known at construction, no build needed
LAT3 = FIXED3.latency
assert LAT3 == 3 and FIXED0.latency == 0, (LAT3, FIXED0.latency)
assert STARTED.latency == 0 and CAPPED.latency == 0


@hw_func
def through_fixed3(x: uint16_t) -> uint16_t:
    return FIXED3(x)


@hw_func
def through_fixed0(x: uint16_t) -> uint16_t:
    return FIXED0(x)


@hw_func
def through_started(x: uint16_t) -> uint16_t:
    return STARTED(x)


@hw_func
def through_capped(x: uint16_t) -> uint16_t:
    return CAPPED(x)


@hw_func
def two_fixed_same_line(x: uint16_t) -> uint16_t:
    # Two different AUTOPIPELINE objects over one func: each call site keeps
    # its own delay line (3 cycles, then 0 more on the second). During
    # warm-up FIXED3's typed-zero output still passes through FIXED0's +7.
    return FIXED0(FIXED3(x))


NUM_CYCLES = 20


@MAIN
def fixed_latency_self_check() -> uint16_t:
    count: Reg[uint16_t]
    o: uint16_t = FIXED3(count)
    if count >= LAT3:
        sim_assert(
            o == count - LAT3 + 7,
            f"fixed latency wrong: count={count} o={o} expected {count - LAT3 + 7}",
        )
    else:
        sim_assert(o == 0, f"warm-up output not zero: count={count} o={o}")
    if count == NUM_CYCLES:
        sim_finish()
    count += 1
    return o


def test_fixed_latency_delay_line():
    sim_reset()
    outs = [int(sim_call(through_fixed3, i)) for i in range(1, 9)]
    assert outs == [0, 0, 0, 8, 9, 10, 11, 12], outs


def test_zero_fixed_and_unfixed_are_passthrough():
    for func in (through_fixed0, through_started, through_capped):
        sim_reset()
        outs = [int(sim_call(func, i)) for i in range(1, 5)]
        assert outs == [8, 9, 10, 11], (func, outs)


def test_nested_call_sites_keep_separate_delay_lines():
    sim_reset()
    outs = [int(sim_call(two_fixed_same_line, i)) for i in range(1, 7)]
    assert outs == [7, 7, 7, 15, 16, 17], outs


def test_reset_clears_delay_line():
    sim_reset()
    for i in range(1, 6):
        sim_call(through_fixed3, i)
    sim_reset()
    assert int(sim_call(through_fixed3, 40)) == 0


if __name__ == "__main__":
    test_fixed_latency_delay_line()
    test_zero_fixed_and_unfixed_are_passthrough()
    test_nested_call_sites_keep_separate_delay_lines()
    test_reset_clears_delay_line()
    print("All AUTOPIPELINE fixed latency native sim tests passed.")
