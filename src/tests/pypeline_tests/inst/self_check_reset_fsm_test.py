# pyright: reportInvalidTypeForm=none
"""Self-checking test of a synchronous reset of an AUTO_FSM: dut sends cases
to OPS_FSM one at a time and checks each result, under
reset_registers="all" with gen_rst, a reset Wire the MAIN rst_gen pulses
while the third case is in flight (and in cycle 0, so the VHDL registers
start from known values). The reset sends the FSM back to idle and dut back
to case 0: a result of the cancelled case would not match case 0 and fail
the check, and a FSM that does not restart would never answer again. rst_gen
counts the results and finishes after N_RESULTS, a cycle after the last print.

The testbench reacts to o.valid instead of counting cycles, so it is correct
at any FSM latency: 0 in a --comb build, where the call site is a
combinational passthrough, and the scheduled latency in a sky130 build.

Registered in native_vs_vhdl_sim_tests.py twice (--comb and a sky130 build),
each diffing native and cocotb+GHDL sim_print(debug=True) output.
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import (
    AUTO_FSM,
    MAIN,
    NamedTuple,
    Reg,
    Wire,
    hw_func,
    int16_t,
    make_clock,
    make_reset,
    sim_assert,
    sim_finish,
    sim_print,
    struct,
    uint1_t,
    uint4_t,
    uint8_t,
)

N_RESULTS = 8


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
    half: int16_t = t3 >> 1
    rv: int16_t = half
    if t3 > 100:
        rv = half + x.a
    return rv


OPS_FSM = AUTO_FSM(mixed_ops)

clk = make_clock(100.0)
gen_rst: Wire[uint1_t] = make_reset()
result_valid: Wire[uint1_t]
quiet: Wire[uint1_t]  # N_RESULTS results seen: no more prints, finish next cycle
in_flight: Wire[uint1_t]
case_out: Wire[uint4_t]


@MAIN(clk)
def rst_gen():
    t: Reg[uint8_t]
    results: Reg[uint8_t]
    fired: Reg[uint1_t]
    stop: Reg[uint1_t]
    # A print and sim_finish() in one cycle are not ordered in VHDL simulation
    # (#361): stop printing first, finish a cycle later
    if stop:
        sim_finish()
    quiet = results >= N_RESULTS
    stop = quiet
    # Reset in cycle 0, and once while the third case is in flight
    pulse: uint1_t = t == 0
    if (results == 2) & in_flight & ~fired:
        pulse = 1
        fired = 1
    gen_rst = pulse
    if result_valid:
        results += 1
    t += 1


@MAIN(clk, reset=gen_rst, reset_registers="all")
def dut() -> int16_t:
    last: Reg[int16_t]
    case_idx: Reg[uint4_t]
    busy: Reg[uint1_t]
    x: case_t
    x.a = case_idx + 1
    x.b = case_idx + 2
    x.c = case_idx + 3
    x.d = case_idx + 4
    s: OPS_FSM.in_stream_t
    s.data = x
    s.valid = 0
    if busy == 0:
        s.valid = 1
        busy = 1
    o = OPS_FSM(s)
    in_flight = busy & ~o.valid
    result_valid = o.valid
    case_out = case_idx
    if o.valid:
        t0: int16_t = (case_idx + 1) + (case_idx + 2)
        t1: int16_t = t0 + (case_idx + 3)
        t2: int16_t = t1 - (case_idx + 4)
        t3: int16_t = t2 + t0
        half: int16_t = t3 >> 1
        want: int16_t = half
        if t3 > 100:
            want = half + (case_idx + 1)
        sim_assert(o.data == want, "AUTO_FSM result does not match its case")
        if quiet == 0:
            sim_print(f"case_idx={case_idx} data={o.data}", debug=True)
        last = o.data
        busy = 0
        case_idx += 1
    return last
