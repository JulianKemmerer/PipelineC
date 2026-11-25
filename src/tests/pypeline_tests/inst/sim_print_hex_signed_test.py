# pyright: reportInvalidTypeForm=none
"""Pypeline's hex() of a signed value prints the same text in native and VHDL
simulation (issue #409).

VHDL's to_hstring prints a negative value's two's complement bits, sign-extended
to whole hex digits: int8_t -1 is "FF", and int6_t -1 is "FF" too, not "3F".
Native simulation used to print a minus sign and the magnitude ("-1",
"-0000800"). The values cover the most negative int32_t, a width that is not a
multiple of 4, and positive signed values as controls.

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
    hex,
    int6_t,
    int8_t,
    int32_t,
    sim_finish,
    sim_print,
    uint1_t,
)


@MAIN
def sim_print_hex_signed():
    done: Reg[uint1_t]
    a: int8_t = -1
    b: int32_t = -0x80000000
    c: int32_t = -0x800
    d: int6_t = -1
    e: int6_t = -32
    f: int6_t = 31
    g: int8_t = 5
    if done:
        sim_finish()
    else:
        sim_print(
            f"a={hex(a)} b={hex(b)} c={hex(c)} d={hex(d)} e={hex(e)} "
            f"f={hex(f)} g={hex(g)}",
            debug=True,
        )
    done = 1
