# pyright: reportInvalidTypeForm=none
# make_stream_auto_multi_cycle: the valid/ready multi-cycle-path wrapper whose
# cycle count is an AUTO_MULTI_CYCLE tag. Native sim checks the handshake follows the
# tag's .latency (start_latency= and fixed latency=); synth_tests.py builds
# the same file with --comb (MULTI_CYCLE constraints require a Xilinx part);
# auto_multi_cycle_unit_test.py parses it to check elaboration and the cache re-parse.
import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "..",
        "..",
        "include",
        "pypeline",
    ),
)

from typing import NamedTuple
from pypeline import (
    MAIN,
    PART,
    struct,
    Reg,
    hw_func,
    sim_call,
    sim_reset,
    uint1_t,
    uint32_t,
)

from stream.stream import make_stream_interface
from stream.stream_multi_cycle import make_stream_auto_multi_cycle

PART("xc7a35ticsg324-1l")


@struct
class my_struct_t(NamedTuple):
    x: uint32_t
    y: uint32_t


@hw_func
def divider(i: my_struct_t) -> uint32_t:
    # Guard divide-by-zero: the launch register holds its zero reset value
    # before any input is accepted.
    safe_y: uint32_t = i.y
    if safe_y == 0:
        safe_y = 1
    return i.x / safe_y


my_struct_intrf = make_stream_interface(my_struct_t)

START_LATENCY = 3
FIXED_LATENCY = 2
divider_auto_multi_cycle, divider_auto_multi_cycle_t = make_stream_auto_multi_cycle(
    divider, start_latency=START_LATENCY, max_latency=8
)
divider_fixed_auto_multi_cycle, divider_fixed_auto_multi_cycle_t = make_stream_auto_multi_cycle(
    divider, latency=FIXED_LATENCY
)


@MAIN(100.0)
@hw_func
def auto_multi_cycle_divider_test_fsm() -> uint1_t:
    x: Reg[uint32_t] = 2
    y: Reg[uint32_t] = 1

    in_stream_if: my_struct_intrf.stream_t
    in_stream_if.data = my_struct_t(x=x, y=y)
    in_stream_if.valid = 1

    f = divider_auto_multi_cycle(
        my_struct_intrf.fwd_t(stream=in_stream_if),
        divider_auto_multi_cycle.out_fb_t(ready=1),
    )
    g = divider_fixed_auto_multi_cycle(
        my_struct_intrf.fwd_t(stream=in_stream_if),
        divider_fixed_auto_multi_cycle.out_fb_t(ready=1),
    )

    if f.stream_in_if.ready:
        x = x + 2
        y = y + 1
        if x == 0:
            x = 2
            y = 1

    # Use both outputs: an unused capture register would be optimized away
    # and its set_multicycle_path would name no cells
    return (f.stream_out_if.stream.data == 2) & (g.stream_out_if.stream.data == 2)


def _check_handshake(func_mcp, expected_latency):
    sim_reset()
    x, y = 12, 4
    launched = False
    accepted_cycle = None
    result = None
    for cycle in range(expected_latency + 6):
        stream_in_if = my_struct_intrf.fwd_t(
            stream=my_struct_intrf.stream_t(
                data=my_struct_t(x=x, y=y), valid=0 if launched else 1
            )
        )
        out = sim_call(func_mcp, stream_in_if, func_mcp.out_fb_t(ready=1))
        if not launched and out.stream_in_if.ready:
            launched = True
            accepted_cycle = cycle
        if out.stream_out_if.stream.valid:
            result = int(out.stream_out_if.stream.data)
            assert launched
            assert cycle - accepted_cycle == expected_latency + 1, (
                f"expected output {expected_latency + 1} cycles after launch, "
                f"got {cycle - accepted_cycle}"
            )
            break
    assert launched, "input was never accepted"
    assert result == 3, f"expected 3, got {result}"


def test_start_latency_handshake():
    assert divider_auto_multi_cycle.mcp.latency == START_LATENCY
    _check_handshake(divider_auto_multi_cycle, START_LATENCY)
    print("test_start_latency_handshake PASS")


def test_fixed_latency_handshake():
    assert divider_fixed_auto_multi_cycle.mcp.latency == FIXED_LATENCY
    _check_handshake(divider_fixed_auto_multi_cycle, FIXED_LATENCY)
    print("test_fixed_latency_handshake PASS")


if __name__ == "__main__":
    test_start_latency_handshake()
    test_fixed_latency_handshake()
    print("All stream_auto_multi_cycle tests passed.")
