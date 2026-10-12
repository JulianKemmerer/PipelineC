# pyright: reportInvalidTypeForm=none
"""Known issue fixture for fixed_auto_pipeline_extra_cuts_test.py.

core's two delay_one calls (@pipeline_latency(1)) already supply the 2 cycles
AUTO_PIPELINE(core, latency=2) asks for, so core needs no compiler cuts. The
`x + 1` branch runs parallel to them.
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import (
    AUTO_PIPELINE,
    MAIN,
    NamedTuple,
    Reg,
    hw_func,
    pipeline_latency,
    struct,
    uint16_t,
)


@struct
class extra_cuts_pair_t(NamedTuple):
    a: uint16_t
    b: uint16_t


@pipeline_latency(1)
def delay_one(x: uint16_t) -> uint16_t:
    saved: Reg[uint16_t]
    result: uint16_t = saved
    saved = x
    return result


@hw_func
def core(x: uint16_t) -> extra_cuts_pair_t:
    d: uint16_t = delay_one(delay_one(x))
    return extra_cuts_pair_t(a=d, b=x + 1)


AP = AUTO_PIPELINE(core, latency=2)


@MAIN
def fixed_auto_pipeline_extra_cuts_top() -> extra_cuts_pair_t:
    count: Reg[uint16_t]
    r: extra_cuts_pair_t = AP(count)
    count += 1
    return r
