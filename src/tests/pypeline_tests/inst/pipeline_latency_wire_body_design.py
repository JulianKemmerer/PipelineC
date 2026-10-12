# pyright: reportInvalidTypeForm=none
"""Known issue: @pipeline_latency(N >= 1) on a body that is only wiring (no
registers, no operators) renders illegal VHDL.

The declaration is trusted; it need not match the body. delay_one below claims
one cycle and implements none. Its entity is still named delay_one_1CLK_*,
and its process sensitivity list ends in the "-- Registers" header with
nothing after it. The final two-character trim then cuts that comment instead
of the last comma, leaving `x,` / `-- Register)`. GHDL rejects that: "name
expected here, found 'is'". C's `#pragma FUNC_LATENCY` on a wire-only body
does the same.

Registered in known_issues_tests.py (expect_fail): the cocotb/GHDL run fails
to compile while the bug is present, and passes once the entity is legal VHDL.
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import MAIN, Reg, pipeline_latency, sim_finish, uint16_t


@pipeline_latency(1)
def wire_body_delay(x: uint16_t) -> uint16_t:
    return x


@MAIN
def pipeline_latency_wire_body_top() -> uint16_t:
    count: Reg[uint16_t]
    r: uint16_t = wire_body_delay(count)
    if count == 3:
        sim_finish()
    count += 1
    return r
