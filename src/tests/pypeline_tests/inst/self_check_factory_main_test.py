# pyright: reportInvalidTypeForm=none
"""@MAINs made by factories, native against VHDL: three counter lanes made in a
loop, each driving its own element of one wire; two stateless lanes made by
one factory, each pushing its own word through its own instance of one
make_stream_fifo FIFO; and a factory closure (not a MAIN) that drives a wire
from a MAIN. A checker MAIN prints every value with sim_print(debug=True)
and finishes one cycle after its last print; it also drives an Output from
all of them, so synthesis keeps them.

Each lane keeps its own registers and FIFO state in native simulation only
because every MAIN runs under its own root instance frame, and its own wire
element because every function has its own wire-claim key; the hardware
has one entity per lane.

Registered in native_vs_vhdl_sim_tests.py, which runs the native (--sim
--comb) and cocotb+GHDL (--cocotb --ghdl) sims and diffs their
sim_print(debug=True) output cycle by cycle, and in synth_tests.py (--comb,
sky130).
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import (
    MAIN,
    Output,
    Reg,
    Wire,
    hw_func,
    sim_finish,
    sim_print,
    uint8_t,
)
from stream.stream_fifo import make_stream_fifo

N_CYCLES = 8

vals: Wire[uint8_t[3]]
outs: Wire[uint8_t[2]]
acc: Wire[uint8_t]
# Keeps every value in the synthesized netlist
digest: Output[uint8_t]


def make_counter_lane(i):
    @hw_func
    def counter_lane():
        n: Reg[uint8_t]
        vals[i] = n
        n += i + 1

    return counter_lane


counter_lanes = [MAIN(make_counter_lane(i), name=f"counter{i}") for i in range(3)]

F = make_stream_fifo(uint8_t, 4)


def make_fifo_lane(i, word):
    @hw_func
    def fifo_lane():
        r = F(
            F.fwd_t(stream=F.stream_intrf.stream_t(data=word, valid=1)),
            F.fb_t(ready=1),
        )
        d: uint8_t = 0
        if r.out_stream_if.stream.valid:
            d = r.out_stream_if.stream.data
        outs[i] = d

    return fifo_lane


MAIN(make_fifo_lane(0, 7), name="fifo_a")
MAIN(make_fifo_lane(1, 9), name="fifo_b")


def make_writer(k):
    @hw_func
    def writer(x: uint8_t):
        acc = x + k

    return writer


add5 = make_writer(5)


@MAIN
def drive():
    t: Reg[uint8_t]
    add5(t)
    t += 1


@MAIN
def check():
    c: Reg[uint8_t]
    if c < N_CYCLES:
        sim_print(
            f"c={c} vals={vals[0]},{vals[1]},{vals[2]} "
            f"outs={outs[0]},{outs[1]} acc={acc}",
            debug=True,
        )
    if c == N_CYCLES:
        sim_finish()
    c += 1
    digest = vals[0] ^ vals[1] ^ vals[2] ^ outs[0] ^ outs[1] ^ acc
