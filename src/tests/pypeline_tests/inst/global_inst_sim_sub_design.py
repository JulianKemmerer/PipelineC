# pyright: reportInvalidTypeForm=none
"""Fixture for global_inst_sim_test.py: a global instance declared in an
imported module. Its driver is here; the importing design reads it as
`global_inst_sim_sub_design.acc.out`."""

from pypeline import MAIN, Inst, Reg, hw_func, uint8_t


@hw_func
def mac(a: uint8_t, b: uint8_t) -> uint8_t:
    return a * 3 + b


acc: Inst[mac]


@MAIN
def acc_driver():
    t: Reg[uint8_t]
    acc.a = t
    acc.b = 5
    t += 1
