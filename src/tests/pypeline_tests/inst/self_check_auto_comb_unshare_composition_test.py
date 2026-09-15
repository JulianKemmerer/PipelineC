"""ACU composed with fixed/discovered pipelines, MCP and default AUTO_FSM."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../include/pypeline")))
from pypeline import (AUTO_COMB_UNSHARE, AUTO_PIPELINE, MAIN, PART, NamedTuple, Reg, hw_func,
    struct, sim_assert, sim_finish, sim_print, uint1_t, uint8_t, uint16_t)
from stream.stream_auto_pipeline import make_stream_auto_pipeline
from stream.stream_auto_fsm import make_stream_auto_fsm
from stream.stream_multi_cycle import make_stream_auto_multi_cycle

PART("xc7a35tcpg236-1")  # MCP timing constraints require Vivado.


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
    mcp: output_t


@hw_func
def core(x: input_t) -> output_t:
    o: output_t
    o.seq = x.seq
    left: uint8_t = x.a if x.sel else x.c
    right: uint8_t = x.b if x.sel else x.d
    o.value = left * right
    return o


ACU = AUTO_COMB_UNSHARE(core)
FIXED = AUTO_PIPELINE(ACU, latency=1)
PIPE, PIPE_T = make_stream_auto_pipeline(ACU)
FSM, FSM_T = make_stream_auto_fsm(core)
EXPLICIT, EXPLICIT_T = make_stream_auto_fsm(ACU)
MCP, MCP_T = make_stream_auto_multi_cycle(ACU, latency=3)


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
            sim_assert(o.stream_out_if.stream.data.seq == received, "ACU composition ordering")
            sim_assert(o.stream_out_if.stream.data.value == expected, "ACU composition value")
            sim_print(f"{name} seq={received} value={o.stream_out_if.stream.data.value}", debug=True)
            received += 1
        sim_assert(cycle < 1000, "ACU composition failed to drain")
        cycle += 1
        # sim_assert/print are synthesis-off. Export the payload so synthesis
        # retains the datapath (including the MCP capture registers).
        result: checker_t
        result.done = received == 8
        result.data = o.stream_out_if.stream.data
        return result
    return checker


CHECK_PIPE = make_checker(PIPE, PIPE_T, 0)
CHECK_FSM = make_checker(FSM, FSM_T, 1)
CHECK_EXPLICIT = make_checker(EXPLICIT, EXPLICIT_T, 2)
CHECK_MCP = make_checker(MCP, MCP_T, 3)


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
        sim_assert(y.seq == expected_seq, "fixed ACU pipeline latency")
        sim_assert(y.value == 6, "fixed ACU pipeline data")
    p: checker_t = CHECK_PIPE()
    f: checker_t = CHECK_FSM()
    e: checker_t = CHECK_EXPLICIT()
    m: checker_t = CHECK_MCP()
    finished = p.done & f.done & e.done & m.done
    cycle += 1
    result: composition_t
    result.fixed = y
    result.pipeline = p.data
    result.fsm = f.data
    result.explicit_fsm = e.data
    result.mcp = m.data
    return result
