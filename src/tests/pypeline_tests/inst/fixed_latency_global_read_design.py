# pyright: reportInvalidTypeForm=none
"""Known-issue fixture: AUTO_PIPELINE(scale, latency=2) where scale reads a
global wire (gain). The build stops with "cannot build the requested latency
-- realized 1 clock(s)"; the same function with gain as a constant builds both
cuts. Registered in known_issues_tests.py (expect_fail) with --comb
--no_synth, which already plans the fixed latency's cuts.
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import AUTO_PIPELINE, MAIN, Reg, Wire, hw_func, uint16_t, uint32_t

gain: Wire[uint16_t]
x_in: Wire[uint16_t]
y_out: Wire[uint32_t]


@hw_func
def scale(x: uint16_t) -> uint32_t:
    return (x * gain + x) + (x + 1)


ap = AUTO_PIPELINE(scale, latency=2)


@MAIN(100.0)
def src():
    t: Reg[uint16_t]
    gain = 3
    x_in = t
    t = t + 1


@MAIN(100.0)
def dut():
    y_out = ap(x_in)


@MAIN(100.0)
def sink() -> uint32_t:
    return y_out
