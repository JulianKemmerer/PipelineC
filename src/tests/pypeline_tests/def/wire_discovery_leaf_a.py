# pyright: reportInvalidTypeForm=none
from typing import NamedTuple
from pypeline import MAIN, Wire, struct, uint1_t


@struct
class pair_t(NamedTuple):
    a: uint1_t
    b: uint1_t


leaf_a_in: Wire[pair_t]
leaf_a_out: Wire[pair_t]


@MAIN
def leaf_a():
    leaf_a_out = pair_t(a=leaf_a_in.b, b=~leaf_a_in.a)
