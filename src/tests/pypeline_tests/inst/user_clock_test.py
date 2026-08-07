# pyright: reportInvalidTypeForm=none
"""Regression test: make_clock() tags a top-level Input[uint1_t] as a clock,
the pypeline equivalent of PipelineC's DECL_INPUT + CLK_MHZ. `pll_clk` should
become a real, fixed-name top-level port instead of the default rate-named
clock port, with an internal clk_85p0 net driven from it.
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import MAIN, Input, uint1_t, make_clock

CLK_RATE_MHZ = 85.0

pll_clk: Input[uint1_t] = make_clock(CLK_RATE_MHZ)


@MAIN(CLK_RATE_MHZ)
def solution(x: uint1_t) -> uint1_t:
    return ~x
