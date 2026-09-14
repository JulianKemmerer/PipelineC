# pyright: reportInvalidTypeForm=none
"""Cycle-accuracy design for pypeline_sim_debug.py: a stateful @MAIN feeding
an AUTO_PIPELINE(func, latency=2) call site every cycle.

A fixed latency is built by every build and emulated by every native sim:
  - --comb: plain native sim delays the call by 2 cycles, and the --comb VHDL
    build places exactly 2 registers inside the call (delays measured for
    just that call site);
  - no --comb: the planned sweep builds exactly 2, the harvested value is 2,
    and the pipelined native sim emulates it.
The in-design sim_assert pins the end-to-end delay (seq == count - LAT) in
both sims independently, and the per-cycle debug diff proves they agree.

Probes live in the stateful (0-latency) MAIN and are valid- AND count-gated
so VHDL's uninitialized warm-up registers are never compared.
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import (
    AUTO_PIPELINE,
    MAIN,
    NamedTuple,
    Reg,
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
class fixed_ap_stream_t(NamedTuple):
    data: uint8_t
    seq: uint16_t
    valid: uint1_t


@hw_func
def fixed_heavy_stream(x: fixed_ap_stream_t) -> fixed_ap_stream_t:
    rv: fixed_ap_stream_t
    a: uint8_t = x.data / ~x.data
    rv.data = (a / (x.data + 1)) ^ x.data
    rv.seq = x.seq
    rv.valid = x.valid
    return rv


FIXED_AP = AUTO_PIPELINE(fixed_heavy_stream, latency=2)
LAT = FIXED_AP.latency  # 2 everywhere: no build needed to know it
START_CHECK = LAT + 2
NUM_CYCLES_RUN = LAT + 30


@MAIN(10.0)
def fixed_ap_tb() -> fixed_ap_stream_t:
    count: Reg[uint16_t]

    i: fixed_ap_stream_t
    i.valid = 1
    i.seq = count
    i.data = (count & 127) + 3  # never 255 (~x would be 0, div by 0)
    o: fixed_ap_stream_t = FIXED_AP(i)

    if o.valid & (count >= START_CHECK) & (count < NUM_CYCLES_RUN):
        sim_assert(
            o.seq == count - LAT,
            f"fixed latency wrong: count={count} seq={o.seq} expected {count - LAT}",
        )
        sim_print(f"fixed ap out data={o.data} seq={o.seq}", debug=True)

    if count == NUM_CYCLES_RUN:
        sim_finish()
    count += 1
    return o
