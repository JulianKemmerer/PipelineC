# pyright: reportInvalidTypeForm=none
from pypeline import *


@struct
class pmod8_t(NamedTuple):
    """Generic 8-data-pin PMOD connector (upper row p1-p4, lower row p5-p8)."""

    p1: uint1_t
    p2: uint1_t
    p3: uint1_t
    p4: uint1_t
    p5: uint1_t
    p6: uint1_t
    p7: uint1_t
    p8: uint1_t
