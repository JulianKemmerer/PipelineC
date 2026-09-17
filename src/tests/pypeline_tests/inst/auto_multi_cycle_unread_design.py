# pyright: reportInvalidTypeForm=none
# A raw AUTO_MULTI_CYCLE tag whose .latency nothing in the design reads (the handshake
# counter is hard-coded): a synthesizing build must refuse it
# (AUTO_MULTI_CYCLE.CHECK_AUTO_MULTI_CYCLE_TAGS_READ). Used by auto_multi_cycle_unit_test.py.
from pypeline import (
    MAIN,
    PART,
    AUTO_MULTI_CYCLE,
    Reg,
    hw_func,
    uint1_t,
    uint8_t,
    uint32_t,
)

PART("xc7a35ticsg324-1l")

MC = AUTO_MULTI_CYCLE(start_latency=2)


@MAIN(100.0)
@hw_func
def auto_multi_cycle_unread_main(x: uint32_t) -> uint1_t:
    launch: Reg[uint32_t, MC.start]
    capture: Reg[uint32_t, MC.end]
    count: Reg[uint8_t]
    rv: uint1_t = 0
    if count == 3:  # should have been MC.latency + 1
        rv = 1
        count = 0
    else:
        count += 1
    capture = launch * 3
    launch = x
    return rv
