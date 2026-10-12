# pyright: reportInvalidTypeForm=none
"""Global wire uses inside pipelined code that native sim refuses
(pypeline.SimPipelineModelError), checked by
global_wire_pipeline_instance_test.py. -D GWP_REFUSAL_CASE selects one:

  nested    a function called inside the pipeline reads a global wire. In
            hardware it reads it at the stage it is placed; native sim
            evaluates the whole body at entry.
  volatile  the pipelined function itself reads a VOLATILE wire, which
            hardware reads at each consumer's stage.

Both use a plain fixed-latency AUTO_PIPELINE (no @pipeline_latency children),
so plain native sim reaches the wire access on the first cycle.
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
    Reg,
    Wire,
    hw_func,
    param,
    sim_finish,
    uint16_t,
)

CASE = param("GWP_REFUSAL_CASE", "nested", choices=("nested", "volatile"))

g: Wire[uint16_t]
gv: Wire[uint16_t, VOLATILE]


@hw_func
def read_g(x: uint16_t) -> uint16_t:
    return x + g


@hw_func
def core(x: uint16_t) -> uint16_t:
    y: uint16_t = x * 3
    z: uint16_t = y * 5
    if CASE == "nested":
        return read_g(z * 7)
    return z * 7 + gv


AP = AUTO_PIPELINE(core, latency=2)


@MAIN
def global_wire_pipeline_refusal_checker() -> uint16_t:
    count: Reg[uint16_t]
    g = count + 100
    gv = count + 200
    r: uint16_t = AP(count)
    if count == 8:
        sim_finish()
    count += 1
    return r
