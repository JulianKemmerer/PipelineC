# pyright: reportInvalidTypeForm=none
"""Design for the AUTO_FSM timing-iteration test (auto_fsm_timing_iter_test.py).

A chain of six adds at a clock goal where the number of adds packed into one
state decides whether the design meets timing. Built with a deliberately LOOSE
--auto_fsm_budget_scale, the first schedule over-packs its states and misses
the clock; the driver must then blame the FSM, shrink its per-state budget,
reschedule into more states, and converge -- the AUTO_FSM analogue of the
throughput sweep adding pipeline stages.

Sized for sky130 (the test builds with --syn_tool sky130). Each add grows the
previous result (t + 2t) instead of taking a new input, so the FSM captures
only 32 input bits. With wide per-add inputs (auto_fsm_tighten_test.py, 142
captured bits) the input-capture enable's fanout is the critical path under
sky130, no schedule changes it, and there is nothing for tightening to fix.
Here the states' add chains are the critical path. Measured at 125 MHz from a
budget scale of 2.5: 1 state 76 MHz, then 2 states 87 and 94 MHz, then
3 states 128.6 MHz. The 120 MHz goal leaves every 1- and 2-state schedule
missing, and the 3-state schedule ~7% of margin.
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
    struct,
    uint1_t,
    uint16_t,
    uint17_t,
    uint19_t,
    uint21_t,
    uint23_t,
    uint25_t,
    uint27_t,
)


@struct
class chain_in_t(NamedTuple):
    a: uint16_t
    b: uint16_t


@hw_func
def grow_chain(x: chain_in_t) -> uint27_t:
    """A strictly sequential chain of six adds, each at a DIFFERENT width, so
    each is its own entity and functional unit. Same-entity operations can
    never share a state, while distinct units CAN chain within one, which puts
    the number of states -- and hence whether the clock is met -- entirely
    under the budget's control."""
    t0: uint17_t = x.a + x.b
    t1: uint19_t = t0 + (t0 << 1)
    t2: uint21_t = t1 + (t1 << 1)
    t3: uint23_t = t2 + (t2 << 1)
    t4: uint25_t = t3 + (t3 << 1)
    t5: uint27_t = t4 + (t4 << 1)
    return t5


CHAIN_FSM = AUTO_FSM(grow_chain)


@MAIN(120.0)
def auto_fsm_timing_iter_top(start: uint1_t, x: chain_in_t) -> uint27_t:
    s: CHAIN_FSM.in_stream_t
    s.data = x
    s.valid = start
    o = CHAIN_FSM(s)
    result: Reg[uint27_t]
    if o.valid:
        result = o.data
    return result
