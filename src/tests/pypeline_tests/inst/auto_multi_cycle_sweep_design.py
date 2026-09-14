# pyright: reportInvalidTypeForm=none
# AUTO_MULTI_CYCLE end to end under a real Vivado sweep (driven by auto_multi_cycle_sweep_test.py):
# a ~16-round add/xor mixing chain far slower than one 100 MHz clock period,
# behind make_stream_auto_multi_cycle. The sweep must raise the multi-cycle
# count until the launch->capture path meets timing, and the design's own
# handshake check (sim_assert in the MAIN) proves the re-elaborated design
# waits exactly as many cycles as the path is constrained for.
#
# Environment (read at import, so each variant is a different design):
#   AUTO_MULTI_CYCLE_SWEEP_START  start_latency= (unset: default start of 1)
#   AUTO_MULTI_CYCLE_SWEEP_MAX    max_latency=   (unset: no cap)
import os

from pypeline import (
    MAIN,
    PART,
    Reg,
    hw_func,
    sim_assert,
    uint1_t,
    uint16_t,
    uint32_t,
)

from stream.stream import make_stream_interface
from stream.stream_multi_cycle import make_stream_auto_multi_cycle

PART("xc7a35ticsg324-1l")


def _env_int(name):
    value = os.environ.get(name)
    return int(value) if value else None


ROUNDS = 16


@hw_func
def mix(x: uint32_t) -> uint32_t:
    acc: uint32_t = x
    for i in range(ROUNDS):
        acc = acc + ((acc << 3) ^ (acc >> 5)) + i
    return acc


word_intrf = make_stream_interface(uint32_t)
mix_mcp, mix_mcp_t = make_stream_auto_multi_cycle(
    mix,
    start_latency=_env_int("AUTO_MULTI_CYCLE_SWEEP_START"),
    max_latency=_env_int("AUTO_MULTI_CYCLE_SWEEP_MAX"),
)


@MAIN(100.0)
@hw_func
def auto_multi_cycle_sweep_main() -> uint32_t:
    x: Reg[uint32_t] = 1
    cycle: Reg[uint16_t]
    accepted_at: Reg[uint16_t]
    launched: Reg[uint1_t]

    in_stream_if: word_intrf.stream_t
    in_stream_if.data = x
    in_stream_if.valid = 1
    f = mix_mcp(word_intrf.fwd_t(stream=in_stream_if), mix_mcp.out_fb_t(ready=1))

    if f.stream_out_if.stream.valid:
        elapsed: uint16_t = cycle - accepted_at
        sim_assert(
            launched & (elapsed == (mix_mcp.mcp.latency + 1)),
            "AUTO_MULTI_CYCLE handshake did not wait latency + 1 cycles",
        )
    if f.stream_in_if.ready:
        accepted_at = cycle
        launched = 1
        x = x + 1
    cycle = cycle + 1
    # Output the full result: an unused capture register (and the launch
    # register feeding only it) would be optimized away, leaving the
    # set_multicycle_path constraint naming no cells
    return f.stream_out_if.stream.data
