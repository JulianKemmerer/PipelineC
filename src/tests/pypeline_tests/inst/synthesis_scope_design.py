# pyright: reportInvalidTypeForm=none
"""Pipeline geometry, blocked bank helpers, opaque text, MCP evidence and a
stand-in for a scheduled AUTO_FSM (marked by the test after parsing)."""

from pypeline import (
    AUTO_PIPELINE,
    MAIN,
    PART,
    Reg,
    hw_func,
    uint1_t,
    uint8_t,
    uint16_t,
    uint24_t,
    uint32_t,
    uint48_t,
    uint64_t,
)
from fifo import make_fifo
from stream.stream import make_stream_interface
from stream.stream_multi_cycle import (
    make_stream_auto_multi_cycle,
    make_stream_multi_cycle,
)

PART("xc7a35ticsg324-1l")


@hw_func
def product_low(x: uint16_t) -> uint16_t:
    product: uint32_t = x * x
    return product >> 8


@hw_func
def shared_math(x: uint16_t) -> uint16_t:
    return product_low(x) + x


pipeline = AUTO_PIPELINE(shared_math, name="scope_pipeline")
required_fifo = make_fifo(uint16_t, 4)
unrelated_fifo = make_fifo(uint8_t, 8)
automatic_mcp = make_stream_auto_multi_cycle(shared_math, name="scope_mcp")
fixed_mcp = make_stream_multi_cycle(shared_math, 3)
MCP_COUNT = automatic_mcp.mcp.latency
word_if = make_stream_interface(uint16_t)


@hw_func
def bank_stage(x: uint16_t, index: uint1_t) -> uint16_t:
    banks: Reg[uint16_t[2]]
    banks[index] = shared_math(x)
    return pipeline(x) ^ banks[index]


@hw_func
def stateful_neighbor(x: uint16_t) -> uint16_t:
    previous: Reg[uint16_t]
    previous = previous + x
    return previous


@hw_func
def opaque_stage(x: uint16_t) -> uint16_t:
    queued = required_fifo(1, x, 1)
    return queued.data_out


@MAIN(80.0)
def pipeline_main(x: uint16_t, index: uint1_t) -> uint16_t:
    return bank_stage(x, index) ^ stateful_neighbor(x) ^ opaque_stage(x)


@MAIN(80.0)
def unrelated_main(x: uint64_t) -> uint8_t:
    count: Reg[uint64_t]
    count = count + x
    queued = unrelated_fifo(1, count, 1)
    return queued.data_out


@MAIN(80.0)
def pure_main(x: uint8_t) -> uint8_t:
    return x * x + x


@MAIN
def goal_less_main(x: uint64_t) -> uint64_t:
    return x + x


@hw_func
def goal_less_math(x: uint64_t) -> uint64_t:
    return x + x


goal_less_pipeline = AUTO_PIPELINE(goal_less_math, name="goal_less_pipeline")


@MAIN
def goal_less_tag_main(x: uint64_t) -> uint64_t:
    return goal_less_pipeline(x)


@hw_func
def fixed_only_math(x: uint24_t) -> uint48_t:
    return x * x + x


fixed_pipeline = AUTO_PIPELINE(fixed_only_math, latency=2, name="fixed_only")


@MAIN
def fixed_only_main(x: uint24_t) -> uint48_t:
    return fixed_pipeline(x)


@hw_func
def fsm_stand_in(x: uint24_t) -> uint24_t:
    # Holds state like a generated AUTO_FSM; its operator is used nowhere else.
    acc: Reg[uint24_t]
    acc = acc ^ (x - 5)
    return acc


@MAIN(80.0)
def fsm_main(x: uint24_t) -> uint24_t:
    return fsm_stand_in(x)


@MAIN(80.0)
def mcp_main(x: uint16_t) -> uint16_t:
    request: word_if.stream_t
    request.data = x
    request.valid = 1
    automatic = automatic_mcp(
        word_if.fwd_t(stream=request), automatic_mcp.out_fb_t(ready=1)
    )
    fixed = fixed_mcp(word_if.fwd_t(stream=request), fixed_mcp.out_fb_t(ready=1))
    return automatic.stream_out_if.stream.data ^ fixed.stream_out_if.stream.data
