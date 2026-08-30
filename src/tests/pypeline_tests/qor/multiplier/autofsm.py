from pypeline import *
from stream.stream_autofsm import make_stream_autofsm
from operators.soft import (
    register_soft_mult,
    register_soft_mult_shift_add,
    register_soft_mult_karatsuba,
)

# Toggle multiplier implementation:
# "inferred" : HDL '*' operator
# "soft" : the current register_soft_mult() default -- carry-save/deferred-carry
#          (docs/SYN_DESIGN.md section 11), NOT shift-and-add anymore
# "soft_shift_add": the PRIOR register_soft_mult() default (full carry-propagate
#          adds), kept reachable
# "soft_karatsuba": Karatsuba
MULT_IMPL = "soft"

if MULT_IMPL == "soft":
    register_soft_mult()
    # Stale -- measured against the OLD (shift-and-add) default, before
    # register_soft_mult() switched to carry-save. Not yet re-measured.
    # cycles, sky130 MHz, sky130 um^2, pypeline estimate MHz
    # 1, 97, 33213, 20
    # 2, 130, 40303, 40
    #
elif MULT_IMPL == "soft_shift_add":
    register_soft_mult_shift_add()
elif MULT_IMPL == "soft_karatsuba":
    register_soft_mult_karatsuba()
elif MULT_IMPL != "inferred":
    raise ValueError(f"unknown MULT_IMPL: {MULT_IMPL}")

@struct
class input_payload_t(NamedTuple):
    a: uint16_t
    b: uint16_t

@struct
class output_payload_t(NamedTuple):
    result: uint32_t

@hw_func
def mult(x: input_payload_t) -> output_payload_t:
    o: output_payload_t
    o.result = x.a * x.b
    return o

# Resource-shared multiplier with a real valid/ready handshake, in place of
# the free-running (AUTOPIPELINE-swept) combinational version's input_ready=1
# no-flow-control passthrough.
MULT_FSM, MULT_FSM_T = make_stream_autofsm(mult)

CLK_RATE_MHZ = 50
PART("sky130")
clk: Input[uint1_t] = make_clock(CLK_RATE_MHZ)
input: Input[MULT_FSM.in_intrf.stream_t]
input_ready: Output[uint1_t]
output: Output[MULT_FSM.out_intrf.stream_t]
output_ready: Input[uint1_t]

@MAIN(CLK_RATE_MHZ)
def solution():
    f = MULT_FSM(
        MULT_FSM.in_fwd_t(stream=input), MULT_FSM.out_fb_t(ready=output_ready)
    )

    input_ready = f.stream_in_if.ready
    output = f.stream_out_if.stream
