# pyright: reportInvalidTypeForm=none
"""Fixture: an async global FIFO whose read clock carries nothing else, for
multi_clock_open_tools_test.py. mon_sink, on mon_clk (MON_MHZ, a -D
parameter), pops the FIFO and drives its output straight to pins, so the
only registers on that clock are the FIFO's own (paths to pins are not
timed): at an unreachable goal its worst path is inside the FIFO, which the
sweep must report as the FIFO's, without adding stages anywhere.
"""

from pypeline import *

src_clk = make_clock(100.0, name="src")
mon_clk = make_clock(param("MON_MHZ", 900.0), name="mon")

mon: Fifo[uint32_t] = global_async_fifo(16, impl="builtin")
MON_DATA: Output[uint32_t]  # the read end, straight to pins
MON_VALID: Output[uint1_t]


@MAIN(src_clk)
def mon_source():
    v: Reg[uint32_t]
    mon.wr.stream.data = v
    mon.wr.stream.valid = 1
    if mon.wr.ready:
        v += 1


@MAIN(mon_clk)
def mon_sink():
    mon.rd.ready = 1
    MON_DATA = mon.rd.stream.data
    MON_VALID = mon.rd.stream.valid
