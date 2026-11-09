# pyright: reportInvalidTypeForm=none
"""Fixture for global_fifo_sim_test.py: a global FIFO declared in an imported
module. Its producer is here; the consumer is in the importing design, which
reaches the read end as `global_fifo_sim_sub_design.e.rd`."""

from pypeline import MAIN, Fifo, Reg, global_fifo, uint1_t, uint8_t, Input, make_clock, make_reset

N_WORDS = 24

e: Fifo[uint8_t] = global_fifo(2)


# Synchronous reset pin (pulsed in cycle 0 by the simulators), the reset of
# the design's clock: every @MAIN and global instance resets with it
rst: Input[uint1_t] = make_reset()
clk = make_clock(25.0, reset=rst)


@MAIN(clk, reset_registers="all")
def e_producer():
    t: Reg[uint8_t]
    n: Reg[uint8_t]
    valid: uint1_t = (t[0] | t[1]) & (n < N_WORDS)
    e.wr.stream.data = n + 200
    e.wr.stream.valid = valid
    if valid & e.wr.ready:
        n += 1
    t += 1
