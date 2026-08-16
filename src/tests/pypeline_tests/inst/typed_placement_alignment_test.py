# pyright: reportInvalidTypeForm=none
"""Cycle-accurate VHDL regression for typed physical pipeline placement.

The pure-comb MAIN deliberately contains equivalent flat and hierarchical
fork/join graphs, a live bypass value, fanout, and wide PLUS/MINUS leaves.
The planned sweep must place concrete output/bit boundaries and the parent
pipeline map must align every reconvergent value and valid bit.  The stateful
checker learns the resulting latency, verifies ordering/data continuously,
and emits debug probes for native-vs-GHDL comparison.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../"))

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
    uint16_t,
)


@struct
class typed_in_t(NamedTuple):
    x: uint16_t
    k: uint16_t
    seq: uint16_t
    valid: uint1_t


@struct
class typed_out_t(NamedTuple):
    flat: uint16_t
    hier: uint16_t
    bypass: uint16_t
    fanout: uint16_t
    seq: uint16_t
    valid: uint1_t


typed_in_wire: Wire[typed_in_t]
typed_out_wire: Wire[typed_out_t]


@hw_func
def hierarchical_kernel(x: uint16_t, k: uint16_t) -> uint16_t:
    base: uint16_t = x + k
    left: uint16_t = base - k
    right: uint16_t = base + x
    # base fans out into both branches and the reconvergent result.
    return (left ^ right) + base


@MAIN(200.0)
def typed_placement_pure_main():
    i: typed_in_t = typed_in_wire
    o: typed_out_t

    # Hierarchical form.
    h: uint16_t = hierarchical_kernel(i.x, i.k)

    # Exactly the same graph written flat: users do not need to provide a
    # helper that happens to be roughly one stage in size.
    flat_base: uint16_t = i.x + i.k
    flat_left: uint16_t = flat_base - i.k
    flat_right: uint16_t = flat_base + i.x
    f: uint16_t = (flat_left ^ flat_right) + flat_base

    o.flat = f
    o.hier = h
    o.bypass = i.x
    o.fanout = f ^ h ^ i.x
    o.seq = i.seq
    o.valid = i.valid
    typed_out_wire = o


NUM_CHECK = 24
MAX_CYCLES = 160


@MAIN
def typed_placement_checker() -> typed_out_t:
    count: Reg[uint16_t]
    seen: Reg[uint16_t]
    latency: Reg[uint16_t]
    done: Reg[uint1_t]
    if done:
        sim_finish()

    i: typed_in_t
    i.x = (count * 13) + 5
    i.k = (count & 15) + 1
    i.seq = count
    i.valid = 1
    typed_in_wire = i

    o: typed_out_t = typed_out_wire
    if o.valid & ~done:
        if seen == 0:
            latency = count - o.seq
        else:
            sim_assert(o.seq == count - latency, "typed placement reordered data")
        sim_assert(o.flat == o.hier, "flat/hier fork-join results differ")
        sim_assert(o.bypass == (o.seq * 13) + 5, "live bypass misaligned")
        sim_assert(o.fanout == o.bypass, "fanout/reconvergence misaligned")
        sim_print(
            f"typed out seq={o.seq} flat={o.flat} hier={o.hier} "
            f"bypass={o.bypass} fanout={o.fanout}",
            debug=True,
        )
        if seen == NUM_CHECK - 1:
            done = 1
        seen += 1

    sim_assert(count < MAX_CYCLES, "typed placement pipeline did not flush")
    count += 1
    return o
