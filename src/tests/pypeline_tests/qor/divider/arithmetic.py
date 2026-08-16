"""Arithmetic radix-2 Divider QoR fixture.

The 32-step restoring division and external stream interface are unchanged
from the investigation input.  Run this only through
``divider_qor_bench.py`` so timing and exact-final-VHDL correctness are
recorded together.
"""
from pypeline import *
from stream.stream import make_stream_t

@struct
class input_payload_t(NamedTuple):
    dividend: uint32_t
    divisor: uint32_t

@struct
class output_payload_t(NamedTuple):
    v1: uint32_t
    v2: uint32_t

input_stream_t = make_stream_t(input_payload_t)
output_stream_t = make_stream_t(output_payload_t)

CLK_RATE_MHZ = 143.0
PART("sky130_fd_sc_hvl")
clk: Input[uint1_t] = make_clock(CLK_RATE_MHZ)
input: Input[input_stream_t]
input_ready: Output[uint1_t]
output: Output[output_stream_t]

@hw_func
def radix2_div(left: uint32_t, right: uint32_t) -> output_payload_t:
    left_eff: uint32_t = left if right != 0 else 4294967295
    d1: uint34_t = right
    q_out: uint32_t = 0
    remainder: uint32_t = 0
    for i in range(31, -1, -1):
        bits1: uint1_t = left_eff[i]
        rem_ext: uint34_t = concat(0, remainder[31:0], bits1)
        diff1: uint34_t = rem_ext - d1
        q1: uint1_t = ~diff1[33]
        if diff1[33]:
            remainder = rem_ext[31:0]
        else:
            remainder = diff1[31:0]
        q_out = concat(q_out[30:0], q1)

    return output_payload_t(v1=q_out, v2=remainder)

@MAIN(CLK_RATE_MHZ)
def solution():
    output.data = radix2_div(input.data.dividend, input.data.divisor)
    output.valid = input.valid
    input_ready = 1
