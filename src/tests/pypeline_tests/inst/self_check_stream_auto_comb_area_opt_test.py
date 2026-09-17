"""Registered AREA_OPT stream, native/GHDL backpressure and throughput checks."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../include/pypeline")))
from pypeline import (AUTO_COMB_AREA_OPT, MAIN, NamedTuple, Reg, hw_func, struct,
                      sim_assert, sim_finish, sim_print, uint1_t, uint8_t, uint16_t)
from stream.stream_auto_comb_area_opt import make_stream_auto_comb_area_opt


@struct
class input_t(NamedTuple):
    a: uint8_t
    b: uint8_t
    c: uint8_t
    d: uint8_t
    sel: uint1_t


@hw_func
def selected(x: input_t) -> uint16_t:
    return x.a * x.b if x.sel else x.c * x.d


CORE = AUTO_COMB_AREA_OPT(selected)
STREAM, STREAM_T = make_stream_auto_comb_area_opt(CORE)


@MAIN(5.0)
def stream_test() -> uint16_t:
    cycle: Reg[uint16_t]
    sent: Reg[uint8_t]
    received: Reg[uint8_t]
    last: Reg[uint16_t]
    held: Reg[uint16_t]
    stalled: Reg[uint1_t]
    ready:uint1_t = (cycle < 10) | (cycle[2:0] == 7)
    x:input_t
    x.a = sent
    x.b = 3
    x.c = sent
    x.d = 5
    x.sel = sent[0]
    request:STREAM.in_intrf.stream_t
    request.data = x
    request.valid = sent < 24
    o = STREAM(STREAM.in_fwd_t(stream=request), STREAM.out_fb_t(ready=ready))
    if request.valid & o.stream_in_if.ready:
        sent += 1
    if stalled:
        sim_assert(o.stream_out_if.stream.valid, "stalled valid dropped")
        sim_assert(o.stream_out_if.stream.data == held, "stalled data changed")
    stalled = o.stream_out_if.stream.valid & ~ready
    held = o.stream_out_if.stream.data
    if o.stream_out_if.stream.valid & ready:
        expected:uint16_t = received * 5
        if received[0]:
            expected = received * 3
        sim_assert(o.stream_out_if.stream.data == expected, "AREA_OPT stream result/order mismatch")
        if received < 8:
            sim_assert(cycle == received + 2, "AREA_OPT stream latency/II mismatch")
        last = o.stream_out_if.stream.data
        sim_print(f"AREA_OPT received={received} value={last}", debug=True)
        received += 1
    if received == 24:
        # Finish the following cycle so the last debug probe is not lost.
        if ~o.stream_out_if.stream.valid:
            sim_finish()
    sim_assert(cycle < 300, "AREA_OPT stream failed to drain")
    cycle += 1
    return last
