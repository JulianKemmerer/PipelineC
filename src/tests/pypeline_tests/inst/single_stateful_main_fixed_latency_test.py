# pyright: reportInvalidTypeForm=none
"""A design whose ONLY @MAIN is stateful and has no target frequency, calling a
fixed-latency (@pipeline_latency) function it consumes self-timed.

There is nothing to pipeline: a stateful main cannot take added latency. A
pipelined (non---comb) build used to pick the coarse sweep anyway for "single
main with no target MHz" and die in slicing with "Trying to slice into ... for
no reason". It now characterizes the design as written (planned sweep, zero
added latency). The fixed-latency child is incidental -- any single stateful
goal-less MAIN crashed the same way -- but it makes the cycle diff check that
delay3's registers line up the same natively and in real VHDL.

The main returns a value on purpose: a design with no top-level outputs
synthesizes to nothing, which is (correctly) a build error.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))
from pypeline import (
    MAIN,
    Reg,
    pipeline_latency,
    sim_assert,
    sim_finish,
    sim_print,
    uint1_t,
    uint8_t,
    uint16_t,
)


@pipeline_latency(3)
def delay3(x: uint16_t) -> uint16_t:
    r: Reg[uint16_t[3]]
    result: uint16_t = r[2]
    r[2] = r[1]
    r[1] = r[0]
    r[0] = x
    return result


@MAIN
def single_stateful_main_fixed_latency() -> uint16_t:
    c: Reg[uint8_t]
    done: Reg[uint1_t]
    if done:
        sim_finish()
    y: uint16_t = delay3(c + 100)
    # Count-gated past delay3's warm-up registers; no print on the
    # sim_finish() cycle (c == 12)
    if (c >= 3) & (c < 12):
        sim_assert(y == c - 3 + 100, "delay3")
        sim_print(f"c={c} y={y}", debug=True)
    if c == 11:
        done = 1
    c = c + 1
    return y
