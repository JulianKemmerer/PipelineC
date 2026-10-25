# pyright: reportInvalidTypeForm=none
"""Known issue: native simulation gives two hardware instances one shared state
when only a stateless caller tells them apart.

A stateful function's native-sim state (Reg/Feedback, or a @sim_model's) is
keyed by its instance path. A stateless @hw_func pushes no instance frame, so
two of its calls from one MAIN put the stateful callee at the same path:

  - counters(): a stateless wrapper() called twice, each reaching its own Reg
    counter. Native sim gives both calls one counter (a=10 b=10, a=20 b=20);
    GHDL counts each on its own (a=1 b=10, a=2 b=20).
  - fifos(): two make_stream_fifo FIFOs of different types, called on two
    lines of one MAIN. Every make_fifo model is called from the same line of
    stream_fifo, so both get one model state: native sim gives fa=132 (900's
    low byte), GHDL fa=7.

The generated hardware is correct. Separate @MAINs are not affected: each runs
under its own root frame (pypeline_sim._call_main).

Registered in known_issues_tests.py (expect_fail): pypeline_sim_debug.py
reports MISMATCH while the bug is present, MATCH once it is fixed.
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..",
        "include", "pypeline",
    ),
)

from pypeline import MAIN, Reg, Wire, hw_func, sim_finish, sim_print, uint8_t, uint16_t
from stream.stream_fifo import make_stream_fifo


@hw_func
def counter(step: uint8_t) -> uint8_t:
    n: Reg[uint8_t]
    rv = n
    n += step
    return rv


@hw_func
def wrapper(step: uint8_t) -> uint8_t:  # stateless: no Reg of its own
    return counter(step)


a: Wire[uint8_t]
b: Wire[uint8_t]


@MAIN
def counters():
    a = wrapper(1)  # its own counter: 0, 1, 2, ...
    b = wrapper(10)  # its own counter: 0, 10, 20, ...


F8 = make_stream_fifo(uint8_t, 4)
F16 = make_stream_fifo(uint16_t, 8)
fa: Wire[uint8_t]
fb: Wire[uint16_t]


@MAIN
def fifos():
    ra = F8(F8.fwd_t(stream=F8.stream_intrf.stream_t(data=7, valid=1)), F8.fb_t(ready=1))
    rb = F16(
        F16.fwd_t(stream=F16.stream_intrf.stream_t(data=900, valid=1)), F16.fb_t(ready=1)
    )
    fa = ra.out_stream_if.stream.data
    fb = rb.out_stream_if.stream.data


@MAIN
def check():
    t: Reg[uint8_t]
    if t < 5:
        sim_print(f"t={t} a={a} b={b} fa={fa} fb={fb}", debug=True)
    if t == 6:  # one cycle after the last print
        sim_finish()
    t += 1
