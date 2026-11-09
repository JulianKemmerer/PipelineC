# pyright: reportInvalidTypeForm=none
"""Fixture for global_inst_sim_test.py: a global instance declared in an
imported module. Its driver is here; the importing design reads it as
`global_inst_sim_sub_design.acc.out`."""

from pypeline import MAIN, Inst, Reg, hw_func, uint8_t, Input, make_clock, make_reset, uint1_t


@hw_func
def mac(a: uint8_t, b: uint8_t) -> uint8_t:
    return a * 3 + b


acc: Inst[mac]


# Synchronous reset pin (pulsed in cycle 0 by the simulators), the reset of
# the design's clock: every @MAIN and global instance resets with it
rst: Input[uint1_t] = make_reset()
clk = make_clock(25.0, reset=rst)


@MAIN(clk, reset_registers="all")
def acc_driver():
    t: Reg[uint8_t]
    acc.a = t
    acc.b = 5
    t += 1
