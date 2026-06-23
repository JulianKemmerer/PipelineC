# pyright: reportInvalidTypeForm=none
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

from stream.stream import make_stream_t
from multi_cycle_path import make_valid_ready_mcp

# Translated from examples/mcp/mcp_divider.c — Arty A7-35T, MULTI_CYCLE
# constraints require Vivado synthesis for now.
PART("xc7a35ticsg324-1l")


@struct
class my_struct_t(NamedTuple):
    x: uint32_t
    y: uint32_t


@hw_func
def divider(i: my_struct_t) -> uint32_t:
    # capture_next = func(launch) is computed unconditionally every cycle
    # (including before any real input has been launched, while the internal
    # `launch` register still holds its zero reset value) — guard against
    # dividing by zero so the wrapped function is well-defined for every
    # reachable register state, not just the ones a caller intends to use.
    safe_y: uint32_t = i.y
    if safe_y == 0:
        safe_y = 1
    return i.x / safe_y


my_struct_stream_t = make_stream_t(my_struct_t)

divider_mcp, divider_mcp_t = make_valid_ready_mcp(divider, 16)


# ── examples/mcp/mcp_divider.c's main() FSM, driving divider_mcp directly ──
@MAIN(100.0)
@hw_func
def mcp_divider_test_fsm() -> uint1_t:
    x: Reg[uint32_t] = 2
    y: Reg[uint32_t] = 1
    result: Reg[uint32_t]

    in_stream: my_struct_stream_t
    in_stream.data = my_struct_t(x=x, y=y)
    in_stream.valid = 1

    f = divider_mcp(in_stream, 1)

    if f.ready_for_stream_in:
        x = x + 2
        y = y + 1
        if x == 0:
            x = 2
            y = 1

    if f.stream_out.valid:
        result = f.stream_out.data

    return f.stream_out.data == 2


# ── simulation tests ─────────────────────────────────────────────────────────
# MULTI_CYCLE[...] has no effect on simulation (synthesis timing hint only),
# so divider_mcp's data path settles "instantly" each cycle in sim_call; only
# the valid/ready handshake timing (cycles_since_launch) is actually being
# exercised here.


def test_divider_mcp_handshake():
    sim_reset()
    NCYCLES = 16
    x, y = 2, 1
    launched = False
    accepted_cycle = None
    result = None
    for cycle in range(NCYCLES + 5):
        stream_in = my_struct_stream_t(
            data=my_struct_t(x=x, y=y), valid=0 if launched else 1
        )
        out = sim_call(divider_mcp, stream_in, 1)
        if not launched and out.ready_for_stream_in:
            launched = True
            accepted_cycle = cycle
        if out.stream_out.valid:
            result = int(out.stream_out.data)
            assert launched
            assert (
                cycle - accepted_cycle == NCYCLES + 1
            ), f"expected output {NCYCLES + 1} cycles after launch, got {cycle - accepted_cycle}"
            break
    assert launched, "input was never accepted"
    assert result == 2, f"expected 2, got {result}"
    print(f"test_divider_mcp_handshake PASS  result={result}")


if __name__ == "__main__":
    test_divider_mcp_handshake()
    print("All valid_ready_mcp tests passed.")
