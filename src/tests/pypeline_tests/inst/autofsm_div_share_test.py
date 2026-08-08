# pyright: reportInvalidTypeForm=none
"""Design for the AUTOFSM minimum-area verification test
(autofsm_min_area_verify_test.py): the OPEN showcase.

Three unsigned divides. A divider is the most expensive thing the area model
knows about (AREA_PER_BIT_PAIR_DIV, ~2.5x an adder bit per operand-bit PAIR),
and unlike a multiply it has a soft equivalent AUTOFSM can descend into: a
radix restoring divider is a chain of compare-and-subtract steps built out of
ordinary adders and muxes.

That makes this the design where the area search's OPEN move has something real
to find. Sharing three divides onto one divider (the anchor) still pays for a
whole divider; opening that divider up turns it into subtract/compare steps
that fold onto units the rest of the design already has. Whether that is
actually smaller is the question the verification test answers with yosys cell
counts rather than with the model's own opinion -- the FORCED variants it
builds (--autofsm_open / --autofsm_unshare) are the alternatives the search
passed over.

Widths are deliberately modest (uint8_t): a radix-1 divider is one step per
quotient bit, so operand width is directly the size of the opened DAG, and the
point here is to make the DECISION observable, not to make the biggest design
that still elaborates.
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
    struct,
    uint1_t,
    uint8_t,
    sim_call,
)


@struct
class div_in_t(NamedTuple):
    a: uint8_t
    b: uint8_t
    c: uint8_t
    d: uint8_t
    e: uint8_t
    f: uint8_t


@hw_func
def div3(x: div_in_t) -> uint8_t:
    """Three divides and two adds, all one width so all three divides bind to
    one shared unit by default."""
    q0: uint8_t = x.a / x.b
    q1: uint8_t = x.c / x.d
    q2: uint8_t = x.e / x.f
    s0: uint8_t = q0 + q1
    s1: uint8_t = s0 + q2
    return s1


DIV_FSM = AUTOFSM(div3)


# A LOW clock goal, and that is the entire point of this design rather than an
# afterthought. At a high goal a whole divider does not fit in one state, so the
# scheduler descends into it whether or not that saves area (BUILD_DAG's
# too_slow_for_a_state) and the area search never gets a say. Here the budget is
# big enough to hold a divider, so sharing one whole is the anchor and opening
# it up is a decision the search has to make on area grounds -- which is exactly
# the real case this is about: a design that wants area, not speed.
@MAIN(1.0)
def autofsm_div_share_top(start: uint1_t, x: div_in_t) -> uint8_t:
    s: DIV_FSM.in_stream_t
    s.data = x
    s.valid = start
    o = DIV_FSM(s)
    result: Reg[uint8_t]
    if o.valid:
        result = o.data
    return result


def _model(a, b, c, d, e, f):
    q0 = a // b if b else 0
    q1 = c // d if d else 0
    q2 = e // f if f else 0
    return (q0 + q1 + q2) & 0xFF


if __name__ == "__main__":
    cases = [
        (200, 7, 100, 3, 90, 9),
        (255, 15, 200, 6, 1, 1),
        (0, 5, 77, 11, 240, 100),
    ]
    bad = 0
    for a, b, c, d, e, f in cases:
        got = sim_call(div3, div_in_t(a=a, b=b, c=c, d=d, e=e, f=f))
        want = _model(a, b, c, d, e, f)
        status = "ok" if got == want else "MISMATCH"
        if got != want:
            bad += 1
        print(f"  div3({a},{b},{c},{d},{e},{f}) = {got} (want {want}) {status}")
    print("FAIL" if bad else "All div3 native-sim checks passed.")
    sys.exit(1 if bad else 0)
