# pyright: reportInvalidTypeForm=none
"""Native simulation of global FIFOs, Fifo[T], with each kind of initializer:
global_fifo(n), global_sync_fifo(n), make_stream_fifo(T, n) and
make_skid_buffer(T), plus a FIFO declared in an imported module
(global_fifo_sim_sub_design.e).

Every producer offers N_WORDS numbered words on 3 cycles out of 4 and every
consumer takes one on 1 cycle out of 4, so each FIFO fills and pushes back.
Each consumer checks that the words arrive in order with none lost or
repeated (sim_assert), and each producer records that it saw backpressure.
`a` and `b` build the same make_stream_fifo(uint8_t, 4): their two FIFO MAINs
must still keep separate FIFO state.

Registered in native_sim_tests.py (pypelinec --sim --comb, which also
elaborates every FIFO kind before simulating).
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import (
    MAIN,
    Fifo,
    Reg,
    Wire,
    global_fifo,
    global_sync_fifo,
    sim_assert,
    sim_finish,
    sim_print,
    uint1_t,
    uint8_t,
    uint16_t,
)
from stream.skid_buffer import make_skid_buffer
from stream.stream_fifo import make_stream_fifo

import global_fifo_sim_sub_design as sub

N_WORDS = sub.N_WORDS

a: Fifo[uint8_t] = global_fifo(4)
b: Fifo[uint8_t] = global_sync_fifo(3)  # rounded up: the same FIFO as a's
c: Fifo[uint8_t] = make_stream_fifo(uint8_t, 8)
d: Fifo[uint8_t] = make_skid_buffer(uint8_t)

received: Wire[uint1_t[5]]  # element i: consumer i got every word
pushed_back: Wire[uint1_t[4]]  # element i: producer i saw ready low


@MAIN
def a_producer():
    t: Reg[uint8_t]
    n: Reg[uint8_t]
    stalled: Reg[uint1_t]
    valid: uint1_t = (t[0] | t[1]) & (n < N_WORDS)
    a.wr.stream.data = n + 10
    a.wr.stream.valid = valid
    if valid & a.wr.ready:
        n += 1
    if valid & ~a.wr.ready:
        stalled = 1
    pushed_back[0] = stalled
    t += 1


@MAIN
def a_consumer():
    t: Reg[uint8_t]
    n: Reg[uint8_t]
    ready: uint1_t = t[1] & t[2]
    a.rd.ready = ready
    if ready & a.rd.stream.valid:
        sim_assert(a.rd.stream.data == n + 10, f"a: got {a.rd.stream.data}, expected {n + 10}")
        n += 1
    received[0] = n == N_WORDS
    t += 1


@MAIN
def b_producer():
    t: Reg[uint8_t]
    n: Reg[uint8_t]
    stalled: Reg[uint1_t]
    valid: uint1_t = (t[0] | t[1]) & (n < N_WORDS)
    b.wr.stream.data = n + 50
    b.wr.stream.valid = valid
    if valid & b.wr.ready:
        n += 1
    if valid & ~b.wr.ready:
        stalled = 1
    pushed_back[1] = stalled
    t += 1


@MAIN
def b_consumer():
    t: Reg[uint8_t]
    n: Reg[uint8_t]
    # Out of phase with a's consumer, so the two identical FIFOs hold
    # different contents
    ready: uint1_t = ~t[1] & t[2]
    b.rd.ready = ready
    if ready & b.rd.stream.valid:
        sim_assert(b.rd.stream.data == n + 50, f"b: got {b.rd.stream.data}, expected {n + 50}")
        n += 1
    received[1] = n == N_WORDS
    t += 1


@MAIN
def c_producer():
    t: Reg[uint8_t]
    n: Reg[uint8_t]
    stalled: Reg[uint1_t]
    valid: uint1_t = (t[0] | t[1]) & (n < N_WORDS)
    c.wr.stream.data = n + 90
    c.wr.stream.valid = valid
    if valid & c.wr.ready:
        n += 1
    if valid & ~c.wr.ready:
        stalled = 1
    pushed_back[2] = stalled
    t += 1


@MAIN
def c_consumer():
    t: Reg[uint8_t]
    n: Reg[uint8_t]
    ready: uint1_t = t[1] & t[2]
    c.rd.ready = ready
    if ready & c.rd.stream.valid:
        sim_assert(c.rd.stream.data == n + 90, f"c: got {c.rd.stream.data}, expected {n + 90}")
        n += 1
    received[2] = n == N_WORDS
    t += 1


@MAIN
def d_producer():
    t: Reg[uint8_t]
    n: Reg[uint8_t]
    stalled: Reg[uint1_t]
    valid: uint1_t = (t[0] | t[1]) & (n < N_WORDS)
    d.wr.stream.data = n + 130
    d.wr.stream.valid = valid
    if valid & d.wr.ready:
        n += 1
    if valid & ~d.wr.ready:
        stalled = 1
    pushed_back[3] = stalled
    t += 1


@MAIN
def d_consumer():
    t: Reg[uint8_t]
    n: Reg[uint8_t]
    ready: uint1_t = t[1] & t[2]
    d.rd.ready = ready
    if ready & d.rd.stream.valid:
        sim_assert(d.rd.stream.data == n + 130, f"d: got {d.rd.stream.data}, expected {n + 130}")
        n += 1
    received[3] = n == N_WORDS
    t += 1


@MAIN
def e_consumer():
    t: Reg[uint8_t]
    n: Reg[uint8_t]
    ready: uint1_t = t[1] & t[2]
    sub.e.rd.ready = ready
    if ready & sub.e.rd.stream.valid:
        sim_assert(
            sub.e.rd.stream.data == n + 200,
            f"e: got {sub.e.rd.stream.data}, expected {n + 200}",
        )
        n += 1
    received[4] = n == N_WORDS
    t += 1


@MAIN
def checker():
    t: Reg[uint16_t]
    sim_assert(t < 200, "global_fifo_sim: a FIFO did not deliver every word")
    all_received: uint1_t = received[0] & received[1] & received[2] & received[3]
    all_pushed_back: uint1_t = pushed_back[0] & pushed_back[1] & pushed_back[2]
    if all_received & received[4]:
        sim_assert(
            all_pushed_back & pushed_back[3],
            "global_fifo_sim: a producer saw no backpressure",
        )
        sim_print(f"global_fifo_sim PASS at cycle {t}")
        sim_finish()
    t += 1
