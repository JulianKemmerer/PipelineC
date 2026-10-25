# pyright: reportInvalidTypeForm=none
"""Fixture: a design on two clocks for the multi_clock synthesis tests
(multi_clock_open_tools_test.py, multi_clock_vivado_test.py).

Like multi_clock_design.py, but eth_clk is not bound to a pin, so its port
keeps its clock name, clk_125p0_eth_rx, which is the name the timing reports
use. eth_rx writes a counting byte sequence into the async global FIFO rx,
forward moves it into the sync global FIFO cmds, checker counts it, and the
async flag link_up crosses with two synchronizer registers in the reader.

crunch is a stateless MAIN on CRUNCH_MHZ (a -D parameter) with a 32-bit
multiply: a sweep must cut it to meet a high goal. FIFO_IMPL=builtin makes
rx the built-in async FIFO on Vivado too.
"""

from pypeline import *

eth_clk = make_clock(125.0, name="eth_rx")  # the clock clk_125p0_eth_rx

rx: Fifo[uint8_t] = global_fifo(16, impl=param("FIFO_IMPL", None))
cmds: Fifo[uint8_t] = global_sync_fifo(4)
link_up: Wire[uint1_t, ASYNC]

RX_COUNT: Output[uint8_t]
RX_ERRORS: Output[uint8_t]
LINK: Output[uint1_t]


@MAIN(eth_clk)
def eth_rx():
    n: Reg[uint8_t]
    up: Reg[uint1_t]
    rx.wr.stream.data = n
    rx.wr.stream.valid = 1
    if rx.wr.ready:
        n += 1
    link_up = up
    up = 1


@MAIN(100.0)
def forward():
    sync: Reg[uint1_t[2]]
    LINK = sync[1]
    sync[1] = sync[0]
    sync[0] = link_up
    rx.rd.ready = cmds.wr.ready
    cmds.wr.stream.data = rx.rd.stream.data
    cmds.wr.stream.valid = rx.rd.stream.valid


@MAIN(100.0)
def checker():
    expected: Reg[uint8_t]
    count: Reg[uint8_t]
    errors: Reg[uint8_t]
    RX_COUNT = count
    RX_ERRORS = errors
    cmds.rd.ready = 1
    if cmds.rd.stream.valid:
        if cmds.rd.stream.data != expected:
            errors += 1
        else:
            count += 1
        expected = cmds.rd.stream.data + 1


@MAIN(param("CRUNCH_MHZ", 50.0))
def crunch(x: uint32_t, y: uint32_t) -> uint64_t:
    return x * y + x
