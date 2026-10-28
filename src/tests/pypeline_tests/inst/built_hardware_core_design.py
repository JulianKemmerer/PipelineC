# pyright: reportInvalidTypeForm=none
"""Hardware shared by built_hardware_top_design.py (built with real ports) and
built_hardware_tb_design.py (a native testbench of that build): an
AUTO_PIPELINE region and an AUTO_FSM, each behind its own @MAIN and global
wires, and an AUTO_PIPELINE whose .latency is read but which is never
instantiated. See built_hardware_sim_test.py."""

from pypeline import (
    AUTO_FSM,
    AUTO_PIPELINE,
    MAIN,
    NamedTuple,
    Wire,
    hw_func,
    int16_t,
    param,
    struct,
    uint16_t,
)

GOAL_MHZ = param("GOAL_MHZ", 100, help="Clock goal of both MAINs")


@hw_func
def divide_body(x: uint16_t) -> uint16_t:
    return x / ((x >> 4) | 1)


BODY = AUTO_PIPELINE(divide_body, name="built_hardware_body")


@hw_func
def spare_body(x: uint16_t) -> uint16_t:
    return x * 3


# Read and never instantiated, like a factory's unused alternative: the build
# serves its .latency (the test's hints file seeds it) and builds nothing
SPARE = AUTO_PIPELINE(spare_body, name="built_hardware_spare")
SPARE_LATENCY = SPARE.latency


@struct
class case_t(NamedTuple):
    a: int16_t
    b: int16_t
    c: int16_t
    d: int16_t


@hw_func
def mixed_ops(x: case_t) -> int16_t:
    t0: int16_t = x.a + x.b
    t1: int16_t = t0 + x.c
    t2: int16_t = t1 - x.d
    t3: int16_t = t2 + t0
    return t3 >> 1


OPS_FSM = AUTO_FSM(mixed_ops)

body_in: Wire[uint16_t]  # into the pipelined region
body_out: Wire[uint16_t]  # out of the pipelined region
fsm_in: Wire[OPS_FSM.in_stream_t]  # into the FSM
fsm_out: Wire[OPS_FSM.out_stream_t]  # out of the FSM


@MAIN(GOAL_MHZ)
def body_main():
    body_out = BODY(body_in)


@MAIN(GOAL_MHZ)
def fsm_main():
    fsm_out = OPS_FSM(fsm_in)
