# pyright: reportInvalidTypeForm=none
"""Cycle-accuracy design for pypeline_sim_debug.py WITHOUT --comb: a PURE comb
@MAIN (no AUTOPIPELINE anywhere) that the throughput sweep slices naturally,
plus a stateful checker @MAIN wired to it through global Wire[T]s.

Run (synth_tests.py registers exactly this):
    pypeline_sim_debug.py <this file> --sim --run all
MATCH (exit 0) proves the native sim's write-side MAIN latency emulation
(pypeline._sim_pipelined_main_info) is cycle-accurate against the real
sliced VHDL.

The pipelined MAIN writes ONE output wire whose struct carries the deep data
result together with the echoed seq and valid -- keeping every field on the
same wire keeps the whole wire's VHDL drive stage at the full pipeline depth
(and native's uniform-N write delay exact); a separate shallow side wire
would emerge earlier in VHDL than the uniform model allows (documented
limitation).

The checker learns the pipeline depth k from the first valid output
(k = count - seq, identical in both sims or the debug prints diverge), then
asserts seq continuity at that fixed k -- an exact latency lock in both sims
with no compile-time knowledge of what depth the sweep picks. Probes are
valid-gated: VHDL warm-up outputs are 'U' (gate false), native warm-up wires
hold typed zeros (gate false), so both sims are silent until real data flows.
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import (
    MAIN,
    NamedTuple,
    Reg,
    Wire,
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
class pm_stream_t(NamedTuple):
    data: uint8_t
    seq: uint16_t
    valid: uint1_t


in_wire: Wire[pm_stream_t]
out_wire: Wire[pm_stream_t]


@hw_func
def heavy(x: uint8_t) -> uint8_t:
    return x / ~x


# Pure comb MAIN: no Reg/Feedback state, so the whole MAIN is one cut subtree
# and the planner slices it to meet 50 MHz (same double-division cone as
# sweep_comb_test.py, proven under the PYRTL software timing model).
@MAIN(50.0)
def pipelined_pure_main():
    v: pm_stream_t = in_wire
    o: pm_stream_t
    a: uint8_t = heavy(v.data)
    # XOR the input back in so output data varies per sample (the chained
    # division cone alone is almost always 0 for this input range).
    o.data = heavy(a) ^ v.data
    o.seq = v.seq
    o.valid = v.valid
    out_wire = o


NUM_CHECK = 30
MAX_CYCLES = 200


# Returns the observed pipeline output as a real top-level port: without any
# output, the sweep's per-iteration top synthesis (yosys/PYRTL timing check)
# prunes the entire design as unobserved and the timing analysis fails.
@MAIN
def pm_checker() -> pm_stream_t:
    count: Reg[uint16_t]
    seen: Reg[uint16_t]
    lat_reg: Reg[uint16_t]
    # sim_finish fires the cycle AFTER the last checked output, with prints
    # quiesced (~done gate) -- whether a same-cycle VHDL write flushes before
    # std.env.finish kills GHDL is a process-ordering race the cycle diff
    # must not depend on.
    done: Reg[uint1_t]
    if done:
        sim_finish()

    i: pm_stream_t
    i.valid = 1
    i.seq = count
    i.data = (count & 127) + 3  # 3..130: never 255 (~x would be 0, div by 0)
    in_wire = i

    ov: pm_stream_t = out_wire
    if ov.valid & ~done:
        if seen == 0:
            # Learn the sweep-discovered pipeline depth; printed so the two
            # sims' depths are themselves part of the cycle diff.
            lat_reg = count - ov.seq
            sim_print(f"first out at count={count} seq={ov.seq}", debug=True)
        else:
            sim_assert(
                ov.seq == count - lat_reg,
                f"seq gap: count={count} seq={ov.seq} lat={lat_reg}",
            )
        sim_print(f"pm out data={ov.data} seq={ov.seq}", debug=True)
        if seen == NUM_CHECK - 1:
            done = 1
        seen += 1

    sim_assert(
        count < MAX_CYCLES,
        f"no/too-few outputs within {MAX_CYCLES} cycles: seen={seen}",
    )
    count += 1
    return ov
