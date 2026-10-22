# pyright: reportInvalidTypeForm=none
"""Regression: one function writing fields of two compound global wires of
different struct types. Each written wire gets an implicit zero-init
constant, declared at the function's def line; both constants once had the
same name, so the second wire's type replaced the first's and VHDL writing
failed ("Cant support this assignment in vhdl?"). Two MAINs split each wire's
fields; a checker prints them every cycle.

Registered in native_vs_vhdl_sim_tests.py, which runs the native (--sim --comb)
and cocotb+GHDL (--cocotb --ghdl) sims and diffs their sim_print(debug=True)
output cycle by cycle.
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
    sim_finish,
    sim_print,
    struct,
    uint8_t,
    uint16_t,
)


@struct
class ab_t(NamedTuple):
    a: uint8_t
    b: uint8_t


@struct
class cd_t(NamedTuple):
    c: uint8_t
    d: uint16_t


w1: Wire[ab_t]
w2: Wire[cd_t]
cycle: Wire[uint8_t]  # the checker's cycle count


@MAIN
def drive_first_fields():
    w1.a = cycle
    w2.c = cycle + 1


@MAIN
def drive_second_fields():
    w1.b = 3
    w2.d = 300


@MAIN
def checker():
    t: Reg[uint8_t]
    cycle = t
    if t < 4:
        sim_print(f"t={t} a={w1.a} b={w1.b} c={w2.c} d={w2.d}", debug=True)
    if t == 4:
        sim_finish()
    t += 1
