# pyright: reportInvalidTypeForm=none
"""Self-checking @MAIN test of global instances, Inst[f]: a combinational
instance whose inputs come from two MAINs, two instances of one stateful
counter, a skid buffer instance between a producer and a consumer with
backpressure, an AUTO_PIPELINE(f, latency=2) instance, and a make_ram
instance (a pipeline_latency function, which native sim models without
aligning anything around it: an instance's MAIN takes no added latency). A
checker prints every output each cycle and checks them with sim_assert.

Registered in native_vs_vhdl_sim_tests.py, which runs the native (--sim --comb)
and cocotb+GHDL (--cocotb --ghdl) sims and diffs their sim_print(debug=True)
output cycle by cycle, and in synth_tests.py (--comb, sky130).
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import (
    AUTO_PIPELINE,
    MAIN,
    Inst,
    Output,
    Reg,
    Wire,
    hw_func,
    sim_assert,
    sim_finish,
    sim_print,
    uint1_t,
    uint8_t,
)
from ram import make_ram
from stream.skid_buffer import make_skid_buffer

N_CYCLES = 18


@hw_func
def add(a: uint8_t, b: uint8_t) -> uint8_t:
    return a + b


@hw_func
def counter(step: uint8_t) -> uint8_t:
    n: Reg[uint8_t]
    rv = n
    n += step
    return rv


@hw_func
def plus7(x: uint8_t) -> uint8_t:
    return x + 7


adder: Inst[add]
c1: Inst[counter]
c2: Inst[counter]
sb: Inst[make_skid_buffer(uint8_t)]
piped: Inst[AUTO_PIPELINE(plus7, latency=2)]
ram = make_ram(uint8_t, 8, ports=("rw",), read_latency=1)
mem: Inst[ram]

cycle: Wire[uint8_t]  # the checker's cycle count, for the other MAINs
# Every instance's output folded together: a top-level output keeps the
# instances in the --comb synthesis netlist
checksum: Output[uint8_t]


@MAIN
def drive_a():
    adder.a = cycle
    c1.step = 1
    c2.step = 10


@MAIN
def drive_b():
    adder.b = 5


@MAIN
def producer():
    n: Reg[uint8_t]
    sb.stream_in_if.stream.data = n
    sb.stream_in_if.stream.valid = 1
    if sb.stream_in_if.ready:
        n += 1


@MAIN
def checker():
    t: Reg[uint8_t]
    got: Reg[uint8_t]  # words taken from sb so far
    cycle = t
    piped.x = t
    take: uint1_t = t[0] | t[1]  # ready on 3 cycles out of 4: sb fills
    sb.stream_out_if.ready = take
    sim_assert(adder.out == t + 5, f"adder: got {adder.out} at {t}")
    sim_assert(c1.out == t, f"c1: got {c1.out} at {t}")
    if t >= 2:
        sim_assert(piped.out == t + 5, f"piped: got {piped.out} at {t}")
    if take & sb.stream_out_if.stream.valid:
        sim_assert(sb.stream_out_if.stream.data == got, f"sb: got a word out of order")
        got += 1
    # Write t + 1 to address t for 8 cycles, then read the addresses back
    writing: uint1_t = t < 8
    mem.p0 = ram.p0_in_t(addr=t & 7, wr_data=t + 1, wr_en=writing, valid=1)
    if (t >= 9) & (t <= 16):
        sim_assert(mem.out.p0.rd_data == t - 8, f"mem: got {mem.out.p0.rd_data} at {t}")
    checksum = (
        adder.out ^ c1.out ^ c2.out ^ piped.out ^ sb.stream_out_if.stream.data
        ^ mem.out.p0.rd_data
    )
    # No debug print on the sim_finish() cycle -- whether a same-cycle VHDL
    # write flushes before std.env.finish kills GHDL is a process-ordering
    # race the cycle diff must not depend on.
    if t < N_CYCLES:
        sim_print(
            f"t={t} sum={adder.out} c1={c1.out} c2={c2.out} piped={piped.out} "
            f"sb_valid={sb.stream_out_if.stream.valid} "
            f"sb_data={sb.stream_out_if.stream.data} "
            f"sb_ready={sb.stream_in_if.ready} mem={mem.out.p0.rd_data}",
            debug=True,
        )
    if t == N_CYCLES:
        sim_finish()
    t += 1
