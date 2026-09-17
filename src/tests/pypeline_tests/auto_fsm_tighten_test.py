# pyright: reportInvalidTypeForm=none
"""Design for the AUTO_FSM tighten-stall test (auto_fsm_tighten_stall_test.py).

A long chain of same-type adds, each taking a new wide input. Under sky130 the
FSM's input-capture enable (fanning out to all 142 captured input bits) is the
critical path at every schedule, so tightening the per-state budget can never
help -- which is exactly what the stall test needs: the driver must stop after
the first tightened build that gains no fmax. (The timing-iteration test,
which needs tightening to WORK, uses inst/auto_fsm_timing_iter_design.py,
whose inputs are narrow.)

Kept separate from auto_fsm_test.py so that test's schedule stays the
straightforward one (its assertions are about folding, not about iteration).
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import (
    AUTO_FSM,
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


CHAIN_FSM = AUTO_FSM(long_chain)


@MAIN(40.0)
def auto_fsm_tighten_top(start: uint1_t, x: chain_in_t) -> int26_t:
    s: CHAIN_FSM.in_stream_t
    s.data = x
    s.valid = start
    o = CHAIN_FSM(s)
    result: Reg[int26_t]
    if o.valid:
        result = o.data
    return result
