# pyright: reportInvalidTypeForm=none
from typing import NamedTuple
from pypeline import MAIN, Wire, struct, uint1_t


@struct
class pair_t(NamedTuple):
    a: uint1_t
    b: uint1_t


leaf_b_in: Wire[pair_t]
leaf_b_out: Wire[pair_t]


@MAIN
def leaf_b():
    leaf_b_out = pair_t(a=~leaf_b_in.a, b=leaf_b_in.b)
