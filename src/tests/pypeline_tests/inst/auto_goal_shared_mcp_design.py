"""Fixture for auto_goal_vivado_test.py: one make_stream_auto_multi_cycle
object used under a 50 MHz and a 100 MHz MAIN. One tag has one count, which
must meet both clocks."""
from pypeline import MAIN, PART, Reg, hw_func, uint32_t, Input, make_reset, uint1_t

from stream.stream import make_stream_interface
from stream.stream_multi_cycle import make_stream_auto_multi_cycle

PART("xc7a35ticsg324-1l")


@hw_func
def mix(x: uint32_t) -> uint32_t:
    acc: uint32_t = x
    for i in range(16):
        acc = acc + ((acc << 3) ^ (acc >> 5)) + i
    return acc


word_intrf = make_stream_interface(uint32_t)
mix_mcp = make_stream_auto_multi_cycle(mix)


@hw_func
def lane() -> uint32_t:
    x: Reg[uint32_t] = 1
    in_stream_if: word_intrf.stream_t
    in_stream_if.data = x
    in_stream_if.valid = 1
    f = mix_mcp(word_intrf.fwd_t(stream=in_stream_if), mix_mcp.out_fb_t(ready=1))
    if f.stream_in_if.ready:
        x = x + 1
    return f.stream_out_if.stream.data


# Synchronous reset pins, one per clock (pulsed in cycle 0 by the simulators):
# every @MAIN resets every register with its clock's pin
rst_100: Input[uint1_t] = make_reset()
rst_50: Input[uint1_t] = make_reset()


@MAIN(50.0, reset=rst_50, reset_registers="all")
def slow() -> uint32_t:
    return lane()


@MAIN(100.0, reset=rst_100, reset_registers="all")
def fast() -> uint32_t:
    return lane()
