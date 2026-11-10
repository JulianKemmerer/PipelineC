# pyright: reportInvalidTypeForm=none
"""Known-issue fixture (#391): AUTO_PIPELINE(scale, latency=2) where scale
multiplies two variables. The build stops with "cannot build the requested
latency -- realized 1 clock(s) after planning 2, 3, 4, 5, 6 register
position(s)". Multiplying by a constant, or an adder-only body, builds both
cuts. Registered in known_issues_tests.py (expect_fail) with --comb
--no_synth, which already plans the fixed latency's cuts.
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import AUTO_PIPELINE, MAIN, hw_func, uint16_t, uint32_t


@hw_func
def scale(x: uint16_t) -> uint32_t:
    return (x * x + x) + (x + 1)


ap = AUTO_PIPELINE(scale, latency=2)


@MAIN(100.0)
def dut(x: uint16_t) -> uint32_t:
    return ap(x)
