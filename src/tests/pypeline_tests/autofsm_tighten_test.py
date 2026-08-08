# pyright: reportInvalidTypeForm=none
"""Design for the AUTOFSM timing-iteration test (autofsm_timing_iter_test.py).

A long chain of same-type adds at a clock goal where the number of adds packed
into one state decides whether the design meets timing. Built with a
deliberately LOOSE --autofsm_budget_scale, the first schedule over-packs its
states and misses the clock; the driver must then blame the FSM, shrink its
per-state budget, reschedule into more states, and converge -- the AUTOFSM
analogue of the throughput sweep adding pipeline stages.

Kept separate from autofsm_test.py so that test's schedule stays the
straightforward one (its assertions are about folding, not about iteration).
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import (
    AUTOFSM,
    MAIN,
    NamedTuple,
    Reg,
    hw_func,
    int16_t,
    int18_t,
    int20_t,
    int22_t,
    int24_t,
    int26_t,
    struct,
    uint1_t,
)


@struct
class chain_in_t(NamedTuple):
    a: int16_t
    b: int16_t
    c: int18_t
    d: int20_t
    e: int22_t
    f: int24_t
    g: int26_t


@hw_func
def long_chain(x: chain_in_t) -> int26_t:
    """A strictly sequential chain of six adds, each at a DIFFERENT operand
    width -- so each is a distinct entity and therefore its own functional
    unit. That matters for this test specifically: same-entity operations can
    never share a state (one operation per unit per state is what makes a unit
    shareable at all), so a chain of identical adds would already be one per
    state and the per-state budget would have nothing to decide. Distinct units
    CAN chain within a state, which puts the number of states -- and hence
    whether the clock is met -- entirely under the budget's control.
    """
    t0: int16_t = x.a + x.b
    t1: int18_t = t0 + x.c
    t2: int20_t = t1 + x.d
    t3: int22_t = t2 + x.e
    t4: int24_t = t3 + x.f
    t5: int26_t = t4 + x.g
    return t5


CHAIN_FSM = AUTOFSM(long_chain)


@MAIN(40.0)
def autofsm_tighten_top(start: uint1_t, x: chain_in_t) -> int26_t:
    s: CHAIN_FSM.in_stream_t
    s.data = x
    s.valid = start
    o = CHAIN_FSM(s)
    result: Reg[int26_t]
    if o.valid:
        result = o.data
    return result
