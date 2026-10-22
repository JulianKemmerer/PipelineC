# pyright: reportInvalidTypeForm=none
"""Native simulation of global instances, Inst[f], each checked by
sim_assert in the functions that use it:

- adder, Inst[add]: its two inputs driven from two MAINs, its output read by
  two MAINs, all in the same cycle;
- c1 and c2, two Inst[counter] of one stateful function: each keeps its own
  register (step 1 and step 10);
- sb, Inst[make_skid_buffer(uint8_t)]: an interface-port instance between a
  producer and a consumer with backpressure, words in order;
- piped, Inst[AUTO_PIPELINE(plus7, latency=2)]: its output is its input from
  two cycles earlier, plus 7;
- global_inst_sim_sub_design.acc: an instance declared in an imported module.

Registered in native_sim_tests.py (pypelinec --sim --comb, which also
elaborates every instance before simulating).
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import (
    AUTO_PIPELINE,
    MAIN,
    Inst,
    Reg,
    Wire,
    hw_func,
    sim_assert,
    sim_finish,
    sim_print,
    uint1_t,
    uint8_t,
)
from stream.skid_buffer import make_skid_buffer

import global_inst_sim_sub_design as sub

N_WORDS = 20


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

cycle: Wire[uint8_t]  # the checker's cycle count, for the other MAINs
received: Wire[uint1_t]  # the consumer got every word through sb
pushed_back: Wire[uint1_t]  # the producer saw sb's ready low


@MAIN
def drive_a():
    adder.a = cycle
    c1.step = 1
    c2.step = 10


@MAIN
def drive_b():
    adder.b = cycle + cycle


@MAIN
def read_sum():
    sim_assert(adder.out == cycle * 3, f"adder: got {adder.out} at {cycle}")


@MAIN
def read_sum_again():
    sim_assert(adder.out == cycle + cycle + cycle, "adder: second reader differs")


@MAIN
def producer():
    t: Reg[uint8_t]
    n: Reg[uint8_t]
    stalled: Reg[uint1_t]
    valid: uint1_t = (t[0] | t[1]) & (n < N_WORDS)
    sb.stream_in_if.stream.data = n + 40
    sb.stream_in_if.stream.valid = valid
    if valid & sb.stream_in_if.ready:
        n += 1
    if valid & ~sb.stream_in_if.ready:
        stalled = 1
    pushed_back = stalled
    t += 1


@MAIN
def consumer():
    t: Reg[uint8_t]
    n: Reg[uint8_t]
    ready: uint1_t = t[1] & t[2]
    sb.stream_out_if.ready = ready
    if ready & sb.stream_out_if.stream.valid:
        sim_assert(
            sb.stream_out_if.stream.data == n + 40,
            f"sb: got {sb.stream_out_if.stream.data}, expected {n + 40}",
        )
        n += 1
    received = n == N_WORDS
    t += 1


@MAIN
def checker():
    t: Reg[uint8_t]
    tens: Reg[uint8_t]  # 10 * t, wrapping like c2's own register
    cycle = t
    piped.x = t
    sim_assert(c1.out == t, f"c1: got {c1.out} at {t}")
    sim_assert(c2.out == tens, f"c2: got {c2.out} at {t}")
    if t >= 2:
        sim_assert(piped.out == t - 2 + 7, f"piped: got {piped.out} at {t}")
    sim_assert(sub.acc.out == t * 3 + 5, f"acc: got {sub.acc.out} at {t}")
    sim_assert(t < 200, "global_inst_sim: the skid buffer did not deliver every word")
    if received:
        sim_assert(pushed_back, "global_inst_sim: the producer saw no backpressure")
        sim_print(f"global_inst_sim PASS at cycle {t}")
        sim_finish()
    t += 1
    tens += 10
