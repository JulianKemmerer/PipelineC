# pyright: reportInvalidTypeForm=none
"""Variable-input DSP chain shared by fixed/auto MCPs and an AUTO_PIPELINE call."""
from typing import NamedTuple

from pypeline import (
    AUTO_PIPELINE, MAIN, PART, Reg, hw_func, param, struct,
    uint1_t, uint16_t, uint32_t,
)
from stream.stream import make_stream_interface
from stream.stream_multi_cycle import make_stream_auto_multi_cycle, make_stream_multi_cycle

PART("xc7a200tffg1156-2")
ROUNDS = 3


@struct
class operands_t(NamedTuple):
    a: uint16_t
    b: uint16_t
    salt: uint16_t[2]


@hw_func
def dsp_chain(i: operands_t) -> uint32_t:
    acc: uint32_t = uint32_t(i.salt[0]) | (uint32_t(i.salt[1]) << 16)
    for stage in range(ROUNDS):
        acc = acc * i.a + i.b
    return acc


word_if = make_stream_interface(operands_t)
fixed_mcp, fixed_t = make_stream_multi_cycle(dsp_chain, 4)
auto_mcp, auto_t = make_stream_auto_multi_cycle(
    dsp_chain, start_latency=param("MCP_DSP_START", 1),
)
BODY = AUTO_PIPELINE(dsp_chain)


@struct
class result_t(NamedTuple):
    fixed: fixed_t
    auto: auto_t
    body: uint32_t
    control: uint16_t


@MAIN(80.0)
@hw_func
def mcp_dsp_main(data: operands_t, valid: uint1_t, ready: uint1_t) -> result_t:
    request: word_if.stream_t
    request.data = data
    request.valid = valid
    body_input: Reg[operands_t]
    body_output: Reg[uint32_t]
    control: Reg[uint16_t]
    result: result_t
    result.fixed = fixed_mcp(word_if.fwd_t(stream=request), fixed_mcp.out_fb_t(ready=ready))
    result.auto = auto_mcp(word_if.fwd_t(stream=request), auto_mcp.out_fb_t(ready=ready))
    result.body = body_output
    result.control = control
    body_output = BODY(body_input)
    body_input = data
    control += 1
    return result
