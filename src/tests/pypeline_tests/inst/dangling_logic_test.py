# pyright: reportInvalidTypeForm=none
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

from typing import NamedTuple

from pypeline import (
    MAIN,
    Reg,
    sim_call,
    struct,
    uint1_t,
    uint8_t,
    wires,
)


@MAIN
def dangle_test(c: uint1_t) -> uint8_t:
    r: Reg[uint8_t]
    if c:
        r += 1
    else:
        r -= 1
    return r


if __name__ == "__main__":
    pass
