# pyright: reportInvalidTypeForm=none

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src")
)

from pypeline import (
    Reg,
    MAIN,
    sim_assert,
    sim_finish,
    sim_print,
    uint8_t,
)


@MAIN
def main():
    n: Reg[uint8_t]
    sim_print(f"n={n}")
    sim_assert(n < 100, f"n grew too large: {n}")
    if n >= 3:
        sim_finish()
    n += 1
