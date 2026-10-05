# pyright: reportInvalidTypeForm=none
"""make_stream_auto_pipeline at one word per cycle, checked in native sim and
cocotb+GHDL.

Two wrappers with fixed core latencies 0 and 3 (latency=N is built even in
--comb), each fed by an always-valid producer and drained by an always-ready
consumer. For each, sim_asserts that
- once the first word is accepted, ready stays high until all words are sent;
- result k arrives on cycle first_accept + L + 4 + k: the advertised latency,
  then back to back with no bubble;
- every result is correct.

Registered in native_vs_vhdl_sim_tests.py (cycle diff of the debug probes
between native sim and cocotb+GHDL) and native_sim_tests.py.
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "..",
        "..",
        "include",
        "pypeline",
    ),
)

from pypeline import MAIN, Reg, hw_func, sim_assert, sim_finish, sim_print
from pypeline import uint1_t, uint8_t, uint16_t

from stream.stream_auto_pipeline import make_stream_auto_pipeline


@hw_func
def plus_three(x: uint8_t) -> uint8_t:
    return x + 3


sap0, sap0_t = make_stream_auto_pipeline(plus_three, latency=0)
sap3, sap3_t = make_stream_auto_pipeline(plus_three, latency=3)

NUM = 20  # words through each wrapper
MAX_CYCLES = 100  # every result is due by cycle ~30; a stall fails loudly


@MAIN(100.0)
def self_check_stream_auto_pipeline_ii1() -> uint8_t:
    cycle: Reg[uint16_t]
    sent0: Reg[uint8_t]
    received0: Reg[uint8_t]
    first0: Reg[uint16_t]
    sent3: Reg[uint8_t]
    received3: Reg[uint8_t]
    first3: Reg[uint16_t]
    last: Reg[uint8_t]

    # Read before this cycle's updates: all results were seen on earlier
    # cycles, so no debug probe lands on the sim_finish() cycle.
    finish: uint1_t = (received0 == NUM) & (received3 == NUM)

    # Core latency 0
    in0: sap0.in_intrf.stream_t
    in0.data = sent0
    in0.valid = sent0 < NUM
    o0: sap0_t = sap0(sap0.in_fwd_t(stream=in0), sap0.out_fb_t(ready=1))
    if (sent0 > 0) & in0.valid:
        sim_assert(o0.stream_in_if.ready, f"latency 0: input stalled after {sent0} words")
    if in0.valid & o0.stream_in_if.ready:
        if sent0 == 0:
            first0 = cycle
        sent0 += 1
    if o0.stream_out_if.stream.valid:
        sim_assert(o0.stream_out_if.stream.data == received0 + 3, "latency 0: wrong result")
        sim_assert(cycle == first0 + 4 + received0, f"latency 0: result {received0} late")
        sim_print(
            f"L0 result={received0} value={o0.stream_out_if.stream.data} cycle={cycle}",
            debug=True,
        )
        last = o0.stream_out_if.stream.data
        received0 += 1

    # Core latency 3
    in3: sap3.in_intrf.stream_t
    in3.data = sent3
    in3.valid = sent3 < NUM
    o3: sap3_t = sap3(sap3.in_fwd_t(stream=in3), sap3.out_fb_t(ready=1))
    if (sent3 > 0) & in3.valid:
        sim_assert(o3.stream_in_if.ready, f"latency 3: input stalled after {sent3} words")
    if in3.valid & o3.stream_in_if.ready:
        if sent3 == 0:
            first3 = cycle
        sent3 += 1
    if o3.stream_out_if.stream.valid:
        sim_assert(o3.stream_out_if.stream.data == received3 + 3, "latency 3: wrong result")
        sim_assert(cycle == first3 + 7 + received3, f"latency 3: result {received3} late")
        sim_print(
            f"L3 result={received3} value={o3.stream_out_if.stream.data} cycle={cycle}",
            debug=True,
        )
        last = o3.stream_out_if.stream.data
        received3 += 1

    if finish:
        sim_finish()
    sim_assert(
        cycle < MAX_CYCLES,
        f"did not finish in {MAX_CYCLES} cycles: L0 {received0}/{NUM}, L3 {received3}/{NUM}",
    )
    cycle += 1
    return last
