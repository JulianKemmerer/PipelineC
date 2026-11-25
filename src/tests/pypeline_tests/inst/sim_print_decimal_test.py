# pyright: reportInvalidTypeForm=none
"""sim_print and sim_assert decimal values print the same text in native and
VHDL simulation, including values that do not fit VHDL's 32-bit integer
(issue #360), and a literal "%" in the message.

Narrower values print through integer'image(to_integer(x)); a uint32_t of 2**31
or more, and any wider integer, used to stop GHDL with "overflow detected".
They now print through the module's to_dec_string. The narrow values at the
edge of integer's range (uint31_t max, int32_t min) are controls for the other
path. The sim_assert message with a wide value never fails, but GHDL must
still compile its to_dec_string.

A literal "%" used to stop the build with "Unsupported printf format: %%".

Registered in native_vs_vhdl_sim_tests.py: pypeline_sim_debug.py fails while
the two simulations print different text.
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import (
    MAIN,
    Reg,
    int32_t,
    int33_t,
    int64_t,
    sim_assert,
    sim_finish,
    sim_print,
    uint2_t,
    uint31_t,
    uint32_t,
    uint64_t,
)


@MAIN
def sim_print_decimal():
    n: Reg[uint2_t]
    # Steps past 2**31: 0x7FFFFFFF, 0x80000000, 0x80000001
    u32: uint32_t = 0x7FFFFFFF + n
    u32_max: uint32_t = 0xFFFFFFFF
    u64_max: uint64_t = 0xFFFFFFFFFFFFFFFF
    i64_min: int64_t = -0x8000000000000000
    i33_min: int33_t = -0x100000000
    i33_max: int33_t = 0xFFFFFFFF
    u31_max: uint31_t = 0x7FFFFFFF
    i32_min: int32_t = -0x80000000
    sim_assert(u64_max != 0, f"u64_max={u64_max} i64_min={i64_min}")
    if n == 3:
        sim_finish()
    else:
        sim_print(
            f"u32={u32} u32_max={u32_max} u64_max={u64_max} i64_min={i64_min} "
            f"i33_min={i33_min} i33_max={i33_max} u31_max={u31_max} "
            f"i32_min={i32_min} n={n}%",
            debug=True,
        )
    n += 1
