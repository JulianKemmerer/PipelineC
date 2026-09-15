# pyright: reportInvalidTypeForm=none
"""A single stateful @MAIN with NO top-level outputs: synthesis optimizes the
whole netlist away. Built by pyrtl_no_timing_paths_build_report_test.py, which
requires the pipelined build to FAIL with a clear "no timing paths" error --
measuring an Fmax of a circuit with no paths must never pass silently.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))
from pypeline import (
    MAIN,
    Reg,
    pipeline_latency,
    sim_assert,
    sim_finish,
    sim_print,
    uint1_t,
    uint8_t,
    uint16_t,
)


@pipeline_latency(3)
def delay3(x: uint16_t) -> uint16_t:
    r: Reg[uint16_t[3]]
    result: uint16_t = r[2]
    r[2] = r[1]
    r[1] = r[0]
    r[0] = x
    return result


@MAIN
def no_outputs_main():
    c: Reg[uint8_t]
    done: Reg[uint1_t]
    if done:
        sim_finish()
    y: uint16_t = delay3(c + 100)
    if (c >= 3) & (c < 12):
        sim_assert(y == c - 3 + 100, "delay3")
        sim_print(f"c={c} y={y}", debug=True)
    if c == 11:
        done = 1
    c = c + 1
