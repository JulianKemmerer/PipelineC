# pyright: reportInvalidTypeForm=none
"""A naturally pipelined pure @MAIN using global wires in its own body
(pypeline_guide.md, "Global wires in pipelined code"), cycle-diffed
native vs pipelined VHDL (native_vs_vhdl_sim, non---comb).

The sweep slices gw_pipelined_main to meet 50 MHz (double division). Its
global reads are sampled at its entry and all of its global writes are
published with its total latency, input/output regs included. So:
  - out_shallow (the input, written from stage 0) and out_deep (the deep
    result) carry the same transaction: separate wires stay aligned.
    Native sim used to refuse a pipelined MAIN writing more than one wire,
    and VHDL drove the shallow one early.
  - w_self is read before this MAIN writes it (zero) and after (the new
    value). The native write collector used to read its old published value
    both times.
The stateful checker learns the pipeline depth from the first valid output
(identical in both sims, or the debug prints diverge), then asserts every
wire against the seq alone. Probes are valid-gated: VHDL warm-up outputs are
'U' and native ones typed zeros, so both sims stay silent until data flows.
"""

import os
import sys

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
class gw_stream_t(NamedTuple):
    data: uint8_t
    seq: uint16_t
    valid: uint1_t


@struct
class gw_self_t(NamedTuple):
    a: uint8_t
    b: uint8_t
    seq: uint16_t
    valid: uint1_t


in_wire: Wire[gw_stream_t]
out_shallow: Wire[gw_stream_t]
out_deep: Wire[gw_stream_t]
w_self: Wire[gw_self_t]


@hw_func
def heavy(x: uint8_t) -> uint8_t:
    return x / ~x


@hw_func
def data_of(seq: uint16_t) -> uint8_t:
    return (seq & 127) + 3  # 3..130: never 255 (~x would be 0, div by 0)


@MAIN(50.0)
def gw_pipelined_main():
    v: gw_stream_t = in_wire
    q: uint8_t = heavy(heavy(v.data)) ^ v.data
    out_shallow = v
    out_deep.data = q
    out_deep.seq = v.seq
    out_deep.valid = v.valid
    prior: uint8_t = w_self.a  # own field, before this MAIN writes it: zero
    w_self.a = q
    w_self.b = w_self.a + 1 + prior  # after writing it: q
    w_self.seq = v.seq
    w_self.valid = v.valid


NUM_CHECK = 30
MAX_CYCLES = 200


@MAIN
def gw_pipelined_main_checker() -> gw_stream_t:
    count: Reg[uint16_t]
    seen: Reg[uint16_t]
    lat_reg: Reg[uint16_t]
    done: Reg[uint1_t]
    if done:
        sim_finish()
    i: gw_stream_t
    i.valid = 1
    i.seq = count
    i.data = data_of(count)
    in_wire = i
    deep: gw_stream_t = out_deep
    shallow: gw_stream_t = out_shallow
    me: gw_self_t = w_self
    if deep.valid & ~done:
        if seen == 0:
            lat_reg = count - deep.seq
            sim_print(f"first out at count={count} seq={deep.seq}", debug=True)
        else:
            sim_assert(
                deep.seq == count - lat_reg,
                f"seq gap: count={count} seq={deep.seq} lat={lat_reg}",
            )
        expect: uint8_t = heavy(heavy(data_of(deep.seq))) ^ data_of(deep.seq)
        expect_b: uint8_t = expect + 1
        sim_assert(deep.data == expect, f"deep data {deep.data} want {expect}")
        sim_assert(
            shallow.valid & (shallow.seq == deep.seq) & (shallow.data == data_of(deep.seq)),
            f"out_shallow seq={shallow.seq} not aligned with out_deep seq={deep.seq}",
        )
        sim_assert(
            me.valid & (me.seq == deep.seq) & (me.a == expect) & (me.b == expect_b),
            f"w_self a={me.a} b={me.b} seq={me.seq} want a={expect} b={expect_b}",
        )
        sim_print(
            f"out seq={deep.seq} deep={deep.data} shallow={shallow.data} "
            f"self={me.a},{me.b}",
            debug=True,
        )
        if seen == NUM_CHECK - 1:
            done = 1
        seen += 1
    sim_assert(
        count < MAX_CYCLES,
        f"no/too-few outputs within {MAX_CYCLES} cycles: seen={seen}",
    )
    count += 1
    return deep
