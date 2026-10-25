# pyright: reportInvalidTypeForm=none
"""Fixture: a design on two clocks, in the shape of the guide's Part IV
example, built by multi_clock_ghdl_test.py and the multi_clock synthesis
tests.

- eth_rx, on the named clock eth_clk (125 MHz, its pin ETH_RX_CLK), writes a
  counting byte sequence into the async global FIFO rx and raises the async
  flag link_up.
- forward, on clk_100p0, synchronizes link_up with two ordinary registers,
  and moves bytes from rx into the synchronous global FIFO cmds.
- checker, also on clk_100p0, reads cmds and counts bytes in and out of
  order on the pins RX_COUNT and RX_ERRORS.

FIFO_IMPL=builtin (a -D parameter) makes rx the built-in async FIFO on every
tool; by default Vivado builds xpm_fifo_async. RX_WORDS sets rx's depth.
"""

from pypeline import *

eth_clk = make_clock(125.0, name="eth_rx")  # the clock clk_125p0_eth_rx
ETH_RX_CLK: Input[uint1_t] = eth_clk  # arrives on this pin

rx: Fifo[uint8_t] = global_fifo(  # async: its ends are on two clocks
    param("RX_WORDS", 16), impl=param("FIFO_IMPL", None)
)
cmds: Fifo[uint8_t] = global_sync_fifo(4)  # both ends on clk_100p0
link_up: Wire[uint1_t, ASYNC]  # a flag between clocks, unsynchronized

RX_COUNT: Output[uint8_t]  # bytes checker received in order
RX_ERRORS: Output[uint8_t]  # bytes checker received out of order
LINK: Output[uint1_t]  # link_up, synchronized into clk_100p0


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
    sync: Reg[uint1_t[2]]  # two ordinary registers synchronize link_up
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
