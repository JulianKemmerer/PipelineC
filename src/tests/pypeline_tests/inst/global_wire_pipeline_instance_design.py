# pyright: reportInvalidTypeForm=none
"""Per-instance timing of global wires inside pipelined code, checked in the
generated hardware (cocotb/GHDL) by global_wire_pipeline_instance_test.py.

A global wire is wired directly to the function instance that uses it, with
no registers, and is aligned with THAT function's own arguments/return. The
function sits at some stage of the enclosing pipeline. Two delay_one calls
(@pipeline_latency(1)) pin the stages inside core (AUTO_PIPELINE latency 2):

  early     read_g called at core stage 0: g from the transaction's entry
  late      read_g called at core stage 2: g two cycles later
  vol       a VOLATILE wire consumed at stage 2 is read live there
  wv / wa   the input wired to a VOLATILE wire (driven at stage 0) and to an
            aligned wire (published with the return at stage 2). Plain
            wiring, so no pipeline cut can land inside the written value: a
            VOLATILE write appears when its value is ready, wherever the
            pipeline's cuts put that.

Native sim cannot model this design and refuses it: it evaluates core's whole
body at entry. The VOLATILE and nested-read refusals are checked separately on
global_wire_pipeline_refusal_design.py, which has no fixed-latency children.
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import (
    AUTO_PIPELINE,
    MAIN,
    VOLATILE,
    NamedTuple,
    Reg,
    Wire,
    hw_func,
    pipeline_latency,
    sim_assert,
    sim_finish,
    sim_print,
    struct,
    uint16_t,
)

LAT = 2
START_CHECK = LAT + 2
END = 24


@struct
class instance_out_t(NamedTuple):
    early: uint16_t
    late: uint16_t
    vol: uint16_t


g: Wire[uint16_t]
gv: Wire[uint16_t, VOLATILE]
wv: Wire[uint16_t, VOLATILE]
wa: Wire[uint16_t]


@pipeline_latency(1)
def delay_one(x: uint16_t) -> uint16_t:
    saved: Reg[uint16_t]
    result: uint16_t = saved
    saved = x
    return result


@hw_func
def read_g(x: uint16_t) -> uint16_t:
    return x + g


@hw_func
def core(x: uint16_t) -> instance_out_t:
    d: uint16_t = delay_one(delay_one(x))  # x again, at core stage 2
    r: instance_out_t
    r.early = read_g(x)  # read_g at stage 0
    r.late = read_g(d)  # read_g at stage 2
    r.vol = d + gv  # VOLATILE consumed at stage 2
    wv = x  # VOLATILE: driven at stage 0
    wa = x  # aligned: published with the return at stage 2
    return r


AP = AUTO_PIPELINE(core, latency=LAT)


@MAIN
def global_wire_pipeline_instance_checker() -> uint16_t:
    count: Reg[uint16_t]
    t: uint16_t = count - LAT  # the transaction core returns this cycle
    g = count + 100
    gv = count + 200
    o: instance_out_t = AP(count)
    if (count >= START_CHECK) & (count < END):
        sim_assert(o.early == t + t + 100, f"early read_g: {o.early}, want g(t)")
        sim_assert(o.late == t + count + 100, f"late read_g: {o.late}, want g(t+2)")
        sim_assert(o.vol == t + count + 200, f"VOLATILE read: {o.vol}, want gv(t+2)")
        sim_assert(wv == count, f"VOLATILE write: {wv}, want this cycle's x")
        sim_assert(wa == t, f"aligned write: {wa}, want x of transaction t")
        sim_print(
            f"count={count} early={o.early} late={o.late} vol={o.vol} wv={wv} wa={wa}"
        )
    if count == END:
        sim_finish()
    count += 1
    return o.early
