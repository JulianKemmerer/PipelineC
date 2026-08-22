"""Arithmetic Divider fixture whose 32-bit MUX banks use a user struct.

The division arithmetic, ports, and results match ``arithmetic.py``.  Only
the divide-by-zero selection and loop-carried remainder selection are wrapped
so the corresponding 32-bit MUX leaves exercise generic packed-type splitting.
"""
from pypeline import *
from stream.stream import make_stream_t


@struct
class wrapped_uint32_t(NamedTuple):
    value: uint32_t


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

CLK_RATE_MHZ = 180.0
PART("sky130_fd_sc_hvl")
clk: Input[uint1_t] = make_clock(CLK_RATE_MHZ)
input: Input[input_stream_t]
input_ready: Output[uint1_t]
output: Output[output_stream_t]


@hw_func
def radix2_div(left: uint32_t, right: uint32_t) -> output_payload_t:
    left_eff: wrapped_uint32_t
    if right != 0:
        left_eff = wrapped_uint32_t(value=left)
    else:
        left_eff = wrapped_uint32_t(value=4294967295)

    d1: uint34_t = right
    q_out: uint32_t = 0
    remainder: wrapped_uint32_t = wrapped_uint32_t(value=0)
    for i in range(31, -1, -1):
        bits1: uint1_t = left_eff.value[i]
        rem_ext: uint34_t = concat(0, remainder.value[31:0], bits1)
        diff1: uint34_t = rem_ext - d1
        q1: uint1_t = ~diff1[33]
        if diff1[33]:
            remainder = wrapped_uint32_t(value=rem_ext[31:0])
        else:
            remainder = wrapped_uint32_t(value=diff1[31:0])
        q_out = concat(q_out[30:0], q1)

    return output_payload_t(v1=q_out, v2=remainder.value)


@MAIN(CLK_RATE_MHZ)
def solution():
    output.data = radix2_div(input.data.dividend, input.data.divisor)
    output.valid = input.valid
    input_ready = 1
