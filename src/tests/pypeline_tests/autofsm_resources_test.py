# pyright: reportInvalidTypeForm=none
"""Design for the AUTOFSM resource-comparison test
(autofsm_resources_compare_test.py).

Deliberately expensive and deliberately repetitive: six multiplies and five
same-width adds, all of which AUTOFSM can fold onto ONE multiplier and ONE
adder. Multiplies are the interesting case because a multiplier costs far more
than the operand multiplexers sharing it requires -- with cheap operations the
mux overhead can eat the win, which is exactly the trade-off the comparison
test measures rather than assumes.

The additions are annotated to a fixed width on purpose. Left to grow
naturally, each sum would be a different operand-width entity, hence a
different functional unit, and nothing would share.
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
    int32_t,
    struct,
    uint1_t,
)


@struct
class mul_in_t(NamedTuple):
    a: int16_t
    b: int16_t
    c: int16_t
    d: int16_t
    e: int16_t
    f: int16_t
    g: int16_t
    h: int16_t
    i: int16_t
    j: int16_t
    k: int16_t
    m: int16_t


@hw_func
def dot6(x: mul_in_t) -> int32_t:
    """Six independent products, summed. As plain combinational logic this is
    six multipliers and five adders running at once; as an FSM it is one
    multiplier and one adder used eleven times."""
    p0: int32_t = x.a * x.b
    p1: int32_t = x.c * x.d
    p2: int32_t = x.e * x.f
    p3: int32_t = x.g * x.h
    p4: int32_t = x.i * x.j
    p5: int32_t = x.k * x.m
    s0: int32_t = p0 + p1
    s1: int32_t = s0 + p2
    s2: int32_t = s1 + p3
    s3: int32_t = s2 + p4
    s4: int32_t = s3 + p5
    return s4


DOT_FSM = AUTOFSM(dot6)


# Low enough that one multiply comfortably fits a state: the point of this
# design is the area comparison, so it must not turn into a timing exercise
# (a multiplier is indivisible -- no number of extra states makes one faster).
@MAIN(12.0)
def autofsm_resources_top(start: uint1_t, x: mul_in_t) -> int32_t:
    s: DOT_FSM.in_stream_t
    s.data = x
    s.valid = start
    o = DOT_FSM(s)
    result: Reg[int32_t]
    if o.valid:
        result = o.data
    return result
