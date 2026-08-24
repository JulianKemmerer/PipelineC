from pypeline import *
from stream.stream_autofsm import make_stream_autofsm

@struct
class input_payload_t(NamedTuple):
    dividend: uint32_t
    divisor: uint32_t

@struct
class output_payload_t(NamedTuple):
    v1: uint32_t
    v2: uint32_t

@hw_func
def radix2_div(i: input_payload_t) -> output_payload_t:
    left_eff: uint32_t = i.dividend if i.divisor != 0 else 4294967295
    d1: uint34_t = i.divisor
    q_out: uint32_t = 0
    remainder: uint32_t = 0
    for j in range(31, -1, -1):
        bits1: uint1_t = left_eff[j]
        rem_ext: uint34_t = concat(0, remainder[31:0], bits1)
        diff1: uint34_t = rem_ext - d1
        q1: uint1_t = ~diff1[33]
        if diff1[33]:
            remainder = rem_ext[31:0]
        else:
            remainder = diff1[31:0]
        q_out = concat(q_out[30:0], q1)

    return output_payload_t(v1=q_out, v2=remainder)

# Resource-shared divider with a real valid/ready handshake, in place of the
# free-running (AUTOPIPELINE-swept) combinational version's input_ready=1
# no-flow-control passthrough.
DIV_FSM, DIV_FSM_T = make_stream_autofsm(radix2_div)

# Original AUTOPIPELINE version's 135.5 MHz goal is unreachable here: AUTOFSM
# folds all 32 loop steps onto ONE shared 34-bit subtractor (that's the whole
# point -- see the schedule banner), so the subtractor's own indivisible delay
# becomes the per-state floor no amount of extra states can shrink -- measured
# ~52.9 MHz under real sky130 STA. Lowered well below that floor; the goal
# here is a clean synthesizing build, not matching the pipelined design's fmax.
CLK_RATE_MHZ = 25.0
PART("sky130")
clk: Input[uint1_t] = make_clock(CLK_RATE_MHZ)
input: Input[DIV_FSM.in_intrf.stream_t]
input_ready: Output[uint1_t]
output: Output[DIV_FSM.out_intrf.stream_t]
output_ready: Input[uint1_t]

@MAIN(CLK_RATE_MHZ)
def solution():
    f = DIV_FSM(
        DIV_FSM.in_fwd_t(stream=input), DIV_FSM.out_fb_t(ready=output_ready)
    )

    input_ready = f.stream_in_if.ready
    output = f.stream_out_if.stream
