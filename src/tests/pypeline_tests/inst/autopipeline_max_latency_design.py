# pyright: reportInvalidTypeForm=none
"""Build fixture for autopipeline_constraints_test.py: an unreachable clock
goal whose only pipelinable logic is a max_latency=1 AUTOPIPELINE call site.
The sweep must build at most 1 register there, stop promptly with a warning
naming the cap (not spin to its iteration limit), and fail the build."""
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

from pypeline import AUTOPIPELINE, MAIN, Reg, hw_func, uint1_t, uint8_t


@hw_func
def capped_core(x: uint8_t) -> uint8_t:
    a: uint8_t = x / ~x
    b: uint8_t = a / (x + 1)
    return b / (a + 1)


CAPPED_AP = AUTOPIPELINE(capped_core, max_latency=1)


@MAIN(1000.0)
def autopipeline_max_latency_main(x: uint8_t) -> uint8_t:
    toggle: Reg[uint1_t]
    toggle = ~toggle
    return CAPPED_AP(x)
