# pyright: reportInvalidTypeForm=none
"""Cycle-accuracy design for pypeline_sim_debug.py WITHOUT --comb: a stateful
@MAIN feeding an AUTOPIPELINE'd (with IO regs) comb stream every cycle.

Run (synth_tests.py registers exactly this):
    pypeline_sim_debug.py <this file> --sim --run all
The tool builds+runs the native sim (AUTOPIPELINE call-site delay-line
emulation) and the cocotb+GHDL sim of the same pipelined build, then diffs
the sim_print(..., debug=True) lines per cycle -- MATCH (exit 0) proves the
native latency emulation is cycle-accurate against the real pipelined VHDL.

The in-design sim_assert additionally pins the exact end-to-end latency in
BOTH sims independently: module-level LAT = AP .latency (a pin-and-confirm
consumer -- pass 2 of the driver bakes the real stage count, and the native
sim's design import sees the same installed cache), and each checked output's
seq must equal count - (1 + LAT + 1). If the emulated delay length ever
disagreed with the built VHDL's, one of the two sims would assert/diverge.

Probes live in the stateful (0-latency) MAIN and are valid- AND count-gated:
during VHDL warm-up the pipeline registers are uninitialized ('U'), so
un-gated data prints could never match native sim's typed zeros -- gated,
both sims are silent until real data flows.
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import (
    MAIN,
    NamedTuple,
    Reg,
    _autopipeline_with_io_regs,
    hw_func,
    sim_assert,
    sim_finish,
    sim_print,
    struct,
    uint1_t,
    uint8_t,
    uint16_t,
)


@struct
class ap_stream_t(NamedTuple):
    data: uint8_t
    seq: uint16_t
    valid: uint1_t


@hw_func
def heavy_stream(x: ap_stream_t) -> ap_stream_t:
    rv: ap_stream_t
    # Two chained divisions: a large sliceable comb cone (same shape as
    # sweep_fsm_autopipeline_test.py, proven to pipeline at 40 MHz under the
    # PYRTL software timing model). XOR the input back in so the output data
    # varies per sample (the division cone alone is almost always 0 for this
    # input range) -- gives the cross-sim data diff real values to compare.
    a: uint8_t = x.data / ~x.data
    rv.data = (a / (x.data + 1)) ^ x.data
    rv.seq = x.seq
    rv.valid = x.valid
    return rv


AP_FUNC, AP_CALL = _autopipeline_with_io_regs(
    heavy_stream, has_input_reg=True, has_output_reg=True
)
# .latency consumer: 0 on the bootstrap pass / plain native sim; the real
# discovered core depth on the driver's confirm pass AND in the pipelined
# native sim (same installed cache).
LAT = AP_CALL.latency
TOTAL_LAT = 1 + LAT + 1  # input reg + AUTOPIPELINE core + output reg
START_CHECK = TOTAL_LAT + 2  # count-gate past warm-up ('U' regs in VHDL)
NUM_CYCLES_RUN = TOTAL_LAT + 40


# Returns the pipeline output as a real top-level port: without any output,
# the sweep's per-iteration top synthesis (yosys/PYRTL timing check) prunes
# the entire design as unobserved and the timing analysis fails.
@MAIN(40.0)
def ap_tb() -> ap_stream_t:
    count: Reg[uint16_t]

    i: ap_stream_t
    i.valid = 1
    i.seq = count
    i.data = (count & 127) + 3  # 3..130: never 255 (~x would be 0, div by 0)
    o: ap_stream_t = AP_FUNC(i)

    # count < NUM_CYCLES_RUN: no prints on the sim_finish cycle -- whether a
    # same-cycle VHDL write flushes before std.env.finish kills GHDL is a
    # process-ordering race the cycle diff must not depend on.
    if o.valid & (count >= START_CHECK) & (count < NUM_CYCLES_RUN):
        sim_assert(
            o.seq == count - TOTAL_LAT,
            f"latency wrong: count={count} seq={o.seq} expected {count - TOTAL_LAT}",
        )
        sim_print(f"ap out data={o.data} seq={o.seq}", debug=True)

    if count == NUM_CYCLES_RUN:
        sim_finish()
    count += 1
    return o
