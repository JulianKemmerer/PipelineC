# pyright: reportInvalidTypeForm=none
from pypeline import Wire, uint1_t

flag: Wire[uint1_t]


def bump(x: uint1_t) -> uint1_t:
    return ~x
