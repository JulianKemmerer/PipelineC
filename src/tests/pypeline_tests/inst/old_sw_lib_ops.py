# pyright: reportInvalidTypeForm=none
import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "def")
)

from pypeline import MAIN, uint1_t, uint32_t, uint16_t

import pypeline_tests


@MAIN
def gte_main0(x: uint32_t, y: uint16_t) -> uint1_t:
    return x >= y
