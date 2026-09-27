# pyright: reportInvalidTypeForm=none
"""One shared helper in two MAINs, tagged bodies, MCPs, and untagged gaps."""
from pypeline import AUTO_PIPELINE, MAIN, PART, Reg, hw_func, uint16_t, uint32_t
from stream.stream import make_stream_interface
from stream.stream_multi_cycle import make_stream_auto_multi_cycle, make_stream_multi_cycle

PART("xc7a35ticsg324-1l")


@hw_func
def helper(x: uint16_t) -> uint16_t:
    product: uint32_t = x * x
    return (product >> 8) + x


@hw_func
def ap_body(x: uint16_t) -> uint16_t:
    return helper(x)


@hw_func
def prologue(x: uint16_t) -> uint16_t:
    return helper(x)


@hw_func
def epilogue(x: uint16_t) -> uint16_t:
    return helper(x)


@hw_func
def tagged_gap(x: uint16_t) -> uint16_t:
    return x + 7


AP_BODY = AUTO_PIPELINE(ap_body)
AP_GAP = AUTO_PIPELINE(tagged_gap)


@hw_func
def bridge(x: uint16_t) -> uint16_t:
    # Its own helper stays comb: only tagged_gap may absorb latency.
    return helper(x) ^ AP_GAP(x)


word_if = make_stream_interface(uint16_t)
auto_mcp, auto_mcp_t = make_stream_auto_multi_cycle(prologue)
fixed_mcp, fixed_mcp_t = make_stream_multi_cycle(epilogue, 3)


@MAIN(80.0)
def main_a(x: uint16_t) -> uint16_t:
    state: Reg[uint16_t]
    state = x
    stream: word_if.stream_t
    stream.data = state
    stream.valid = 1
    mcp = auto_mcp(word_if.fwd_t(stream=stream), auto_mcp.out_fb_t(ready=1))
    return AP_BODY(x) ^ helper(state) ^ bridge(x) ^ mcp.stream_out_if.stream.data


@MAIN(80.0)
def main_b(x: uint16_t) -> uint16_t:
    state: Reg[uint16_t]
    state = x
    stream: word_if.stream_t
    stream.data = state
    stream.valid = 1
    mcp = fixed_mcp(word_if.fwd_t(stream=stream), fixed_mcp.out_fb_t(ready=1))
    return AP_BODY(x) ^ helper(state) ^ bridge(x) ^ mcp.stream_out_if.stream.data
