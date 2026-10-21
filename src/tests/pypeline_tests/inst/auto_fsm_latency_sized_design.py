# pyright: reportInvalidTypeForm=none
"""Build fixture for auto_fsm_latency_sized_test.py: an AUTO_FSM whose function
is sized from an AUTO_PIPELINE depth, the shape of WireGuard's shared Poly1305
kernels (lane capacity = body depth + 2).

The bootstrap parse reads depth 0, so AUTO_FSM pass 1 schedules the capacity-2
function. At 100 MHz under sky130 the sweep pipelines the divider core (about
58 MHz unpipelined, the same core auto_pipeline_latency_test.py builds), so the
pin-and-confirm pass 2 re-elaboration builds a different function: an AUTO_FSM
call site no earlier pass scheduled.
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "..",
        "..",
        "include",
        "pypeline",
    ),
)
from pypeline import (
    AUTO_FSM,
    MAIN,
    NamedTuple,
    Reg,
    hw_func,
    struct,
    uint1_t,
    uint8_t,
    uint16_t,
)

from stream.stream import make_stream_interface
from stream.stream_auto_pipeline import make_stream_auto_pipeline


@hw_func
def div_inv(x: uint8_t) -> uint8_t:
    return x / ~x


uint8_stream_intrf = make_stream_interface(uint8_t)
div_core = make_stream_auto_pipeline(div_inv)
# Read during elaboration: 2 on the bootstrap parse, more once the sweep
# pipelines the divider.
CAPACITY = div_core.auto_pipeline.latency + 2


def make_lane_sum(capacity):
    @struct
    class lanes_t(NamedTuple):
        values: uint8_t[capacity]

    @hw_func
    def lane_sum(x: lanes_t) -> uint16_t:
        total: uint16_t = 0
        for i in range(capacity):
            total = total + x.values[i]
        return total

    return lanes_t, lane_sum


lanes_t, lane_sum = make_lane_sum(CAPACITY)
LANE_SUM_FSM = AUTO_FSM(lane_sum)


@MAIN(100.0)
def latency_sized_core_top(
    stream_in_if: uint8_stream_intrf.fwd_t, stream_out_if: uint8_stream_intrf.fb_t
) -> div_core.return_t:
    return div_core(stream_in_if, stream_out_if)


@MAIN(100.0)
def latency_sized_fsm_top(start: uint1_t, x: lanes_t) -> uint16_t:
    s: LANE_SUM_FSM.in_stream_t
    s.data = x
    s.valid = start
    o = LANE_SUM_FSM(s)
    result: Reg[uint16_t]
    if o.valid:
        result = o.data
    return result
