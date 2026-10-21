# pyright: reportInvalidTypeForm=none
"""Fixture for global_fifo_sim_test.py: a global FIFO declared in an imported
module. Its producer is here; the consumer is in the importing design, which
reaches the read end as `global_fifo_sim_sub_design.e.rd`."""

from pypeline import MAIN, Fifo, Reg, global_fifo, uint1_t, uint8_t

N_WORDS = 24

e: Fifo[uint8_t] = global_fifo(2)


@MAIN
def e_producer():
    t: Reg[uint8_t]
    n: Reg[uint8_t]
    valid: uint1_t = (t[0] | t[1]) & (n < N_WORDS)
    e.wr.stream.data = n + 200
    e.wr.stream.valid = valid
    if valid & e.wr.ready:
        n += 1
    t += 1
