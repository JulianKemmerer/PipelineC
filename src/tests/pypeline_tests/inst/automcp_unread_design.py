# pyright: reportInvalidTypeForm=none
# A raw AUTOMCP tag whose .latency nothing in the design reads (the handshake
# counter is hard-coded): a synthesizing build must refuse it
# (SYN.CHECK_AUTOMCP_TAGS_READ). Used by automcp_unit_test.py.
from pypeline import (
    MAIN,
    PART,
    AUTOMCP,
    Reg,
    hw_func,
    uint1_t,
    uint8_t,
    uint32_t,
)

PART("xc7a35ticsg324-1l")

MC = AUTOMCP(start_latency=2)


@MAIN(100.0)
@hw_func
def automcp_unread_main(x: uint32_t) -> uint1_t:
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
