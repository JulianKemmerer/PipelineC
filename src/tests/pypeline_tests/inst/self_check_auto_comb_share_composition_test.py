"""ACS composed with fixed/discovered pipelines and default AUTO_FSM.

No PART: native_vs_vhdl_sim_tests.py picks the tool (--syn_tool pyrtl for the
pipelined build, see NON_COMB_SYN_TOOL there). A make_stream_auto_multi_cycle member used to
live here too, but MULTI_CYCLE constraints are Vivado-only, which forced this
whole design onto a slow Vivado sweep. Multi-cycle composition is covered by
the Vivado-registered stream_*multi_cycle and auto_multi_cycle_sweep tests.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../include/pypeline")))
from pypeline import (AUTO_COMB_SHARE, AUTO_PIPELINE, MAIN, NamedTuple, Reg, hw_func,
    struct, sim_assert, sim_finish, sim_print, uint1_t, uint8_t, uint16_t)
from stream.stream_auto_pipeline import make_stream_auto_pipeline
from stream.stream_auto_fsm import make_stream_auto_fsm


@struct
class input_t(NamedTuple):
    seq: uint8_t
    a: uint8_t
    b: uint8_t
    c: uint8_t
    d: uint8_t
    sel: uint1_t


@struct
class output_t(NamedTuple):
    seq: uint8_t
    value: uint16_t


@struct
class checker_t(NamedTuple):
    done: uint1_t
    data: output_t


@struct
class composition_t(NamedTuple):
    fixed: output_t
    pipeline: output_t
    fsm: output_t
    explicit_fsm: output_t


@hw_func
def core(x: input_t) -> output_t:
    o: output_t
    o.seq = x.seq
    o.value = x.a * x.b if x.sel else x.c * x.d
    return o


ACS = AUTO_COMB_SHARE(core)
FIXED = AUTO_PIPELINE(ACS, latency=1)
PIPE, PIPE_T = make_stream_auto_pipeline(ACS)
FSM, FSM_T = make_stream_auto_fsm(core)
EXPLICIT, EXPLICIT_T = make_stream_auto_fsm(ACS)


def make_checker(stream, t, name):
    @hw_func
    def checker() -> checker_t:
        sent: Reg[uint8_t]
        received: Reg[uint8_t]
        cycle: Reg[uint16_t]
        x: input_t
        x.seq = sent
        x.a = sent
        x.b = 3
        x.c = sent
        x.d = 5
        x.sel = sent[0]
        request: stream.in_intrf.stream_t
        request.data = x
        request.valid = sent < 8
        ready: uint1_t = cycle[1:0] != 0
        o = stream(stream.in_fwd_t(stream=request), stream.out_fb_t(ready=ready))
        if request.valid & o.stream_in_if.ready:
            sent += 1
        if o.stream_out_if.stream.valid & ready:
            expected: uint16_t = received * 5
            if received[0]:
                expected = received * 3
            sim_assert(o.stream_out_if.stream.data.seq == received, "ACS composition ordering")
            sim_assert(o.stream_out_if.stream.data.value == expected, "ACS composition value")
            sim_print(f"{name} seq={received} value={o.stream_out_if.stream.data.value}", debug=True)
            received += 1
        sim_assert(cycle < 1000, "ACS composition failed to drain")
        cycle += 1
        # sim_assert/print are synthesis-off. Export the payload so synthesis
        # retains the datapath.
        result: checker_t
        result.done = received == 8
        result.data = o.stream_out_if.stream.data
        return result
    return checker


CHECK_PIPE = make_checker(PIPE, PIPE_T, 0)
CHECK_FSM = make_checker(FSM, FSM_T, 1)
CHECK_EXPLICIT = make_checker(EXPLICIT, EXPLICIT_T, 2)


@MAIN(5.0)
def composition() -> composition_t:
    cycle: Reg[uint16_t]
    finished: Reg[uint1_t]
    if finished:
        sim_finish()
    x: input_t
    x.seq = cycle
    x.a = 2
    x.b = 3
    x.c = 4
    x.d = 5
    x.sel = 1
    y: output_t = FIXED(x)
    if cycle > 2:
        expected_seq: uint8_t = cycle - 1
        sim_assert(y.seq == expected_seq, "fixed ACS pipeline latency")
        sim_assert(y.value == 6, "fixed ACS pipeline data")
    p: checker_t = CHECK_PIPE()
    f: checker_t = CHECK_FSM()
    e: checker_t = CHECK_EXPLICIT()
    finished = p.done & f.done & e.done
    cycle += 1
    result: composition_t
    result.fixed = y
    result.pipeline = p.data
    result.fsm = f.data
    result.explicit_fsm = e.data
    return result
