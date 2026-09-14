# pyright: reportInvalidTypeForm=none
"""Build fixture for auto_pipeline_constraints_test.py: a fixed latency=2 and
a start_latency=1 AUTO_PIPELINE call site under a stateful @MAIN with an easy
clock goal. Both .latency values are read at import (bootstrap pass), and the
sweep's first iteration builds exactly those counts and meets timing, so the
pypelinec driver must skip the pin-and-confirm re-elaboration (run with
--pipeline_min_effort 0 so trimming can't move the start_latency region)."""
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

from pypeline import AUTO_PIPELINE, MAIN, Reg, hw_func, uint1_t, uint8_t


@hw_func
def fixed_core(x: uint8_t) -> uint8_t:
    a: uint8_t = x / ~x
    return a / (x + 1)


@hw_func
def start_core(x: uint8_t) -> uint8_t:
    a: uint8_t = (x + 3) / ~x
    return a / (x + 2)


FIXED_AP = AUTO_PIPELINE(fixed_core, latency=2)
START_AP = AUTO_PIPELINE(start_core, start_latency=1)
print(
    "auto_pipeline_constraints_design: "
    f"fixed .latency={FIXED_AP.latency} start .latency={START_AP.latency}",
    flush=True,
)


@MAIN(10.0)
def auto_pipeline_constraints_main(x: uint8_t) -> uint8_t:
    # State makes the main itself unsliceable: only the tagged regions take
    # registers
    toggle: Reg[uint1_t]
    toggle = ~toggle
    return FIXED_AP(x) ^ START_AP(x)
