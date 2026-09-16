# pyright: reportInvalidTypeForm=none
"""Design for the AUTO_FSM max_latency test (auto_fsm_max_latency_test.py).

A chain of same-type adds wrapped in `AUTO_FSM(..., max_latency=N)`. Left to
itself the tool shares all of them onto ONE adder and spends one state per add,
which is the smallest design and the longest latency. The cap says: not that
long. The only way to honour it is to give some of the sharing back and build
more than one adder -- which is exactly the trade a latency cap is asking for.

The cap here is deliberately tight enough that the default schedule would blow
straight through it, so the test is about the cap being MET, not about it
happening to be satisfied anyway.

Set PYPELINE_AUTO_FSM_IMPOSSIBLE_LATENCY=1 to build the same design with a cap of
2 (one execution state) at a clock goal where five dependent adds plus their
operand multiplexers do not fit one state. No amount of area shortens a
dependency chain, so the cap is genuinely unreachable and the build must FAIL
loudly rather than quietly returning something slower.
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
    struct,
    uint1_t,
)


@struct
class chain_in_t(NamedTuple):
    a: int16_t
    b: int16_t
    c: int16_t
    d: int16_t
    e: int16_t
    f: int16_t


@hw_func
def add_chain(x: chain_in_t) -> int16_t:
    t0: int16_t = x.a + x.b
    t1: int16_t = t0 + x.c
    t2: int16_t = t1 + x.d
    t3: int16_t = t2 + x.e
    t4: int16_t = t3 + x.f
    return t4


_IMPOSSIBLE = os.environ.get("PYPELINE_AUTO_FSM_IMPOSSIBLE_LATENCY") == "1"

# Sharing all five adds onto one adder costs one state each (one operation per
# unit per state is what makes a unit shareable at all): 5 states, latency 6. A
# cap of 4 therefore cannot be met without building a second adder -- which is
# the whole point of the test. The clock goal is loose enough that two adds DO
# fit one state, so the second adder can actually be used; at a tighter goal the
# delay budget, not the unit count, would be what forces the states.
#
# The goal is sized for sky130 (the test builds with --syn_tool sky130, where an
# int16 add is ~3 ns): 90 MHz leaves a ~10 ns state budget, which two adds plus
# their operand muxes (~8 ns) fit, but the impossible cap's single state of
# five adds (~17 ns) does not. At a loose goal such as 25 MHz all five adds fit
# one sky130 state, and the "impossible" cap would quietly be met.
CHAIN_FSM = AUTO_FSM(add_chain, max_latency=2 if _IMPOSSIBLE else 4)


@MAIN(90.0)
def auto_fsm_max_latency_top(start: uint1_t, x: chain_in_t) -> int16_t:
    s: CHAIN_FSM.in_stream_t
    s.data = x
    s.valid = start
    o = CHAIN_FSM(s)
    result: Reg[int16_t]
    if o.valid:
        result = o.data
    return result
