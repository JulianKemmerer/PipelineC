# pyright: reportInvalidTypeForm=none
"""AUTO_FSM in a design without pins, global wires or clock crossings: its
MAIN has only port arguments. AUTO_FSM measures each generated entity in an
isolated parser state, whose main_mhz names a root instance, not a MAIN
function. That state reaches the per-instance synthesis file list
(SYN.GET_VHDL_FILES_TCL_TEXT_AND_TOP), which must not ask it the whole
design's package question (VHDL.NEEDS_GLOBAL_WIRES_VHDL_PACKAGE). A design
with a pin never gets that far: every pin counts as shared."""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import AUTO_FSM, MAIN, NamedTuple, Reg, hw_func, struct, uint1_t, uint8_t


@struct
class pair_t(NamedTuple):
    a: uint8_t
    b: uint8_t


@hw_func
def two_adds(x: pair_t) -> uint8_t:
    """Two adds of one type, which AUTO_FSM can fold onto one adder."""
    t: uint8_t = x.a + x.b
    rv: uint8_t = t + x.a
    return rv


TWO_ADDS_FSM = AUTO_FSM(two_adds)


@MAIN(25.0)
def auto_fsm_no_pins_top(start: uint1_t, x: pair_t) -> uint8_t:
    s: TWO_ADDS_FSM.in_stream_t
    s.data = x
    s.valid = start
    o = TWO_ADDS_FSM(s)
    result: Reg[uint8_t]
    if o.valid:
        result = o.data
    return result
