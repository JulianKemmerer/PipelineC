# pyright: reportInvalidTypeForm=none
from typing import NamedTuple
from pypeline import MAIN, Wire, struct, uint1_t

i: Wire[uint1_t]
o: Wire[uint1_t]


@struct
class pair_t(NamedTuple):
    a: uint1_t
    b: uint1_t
    bits: uint1_t[2]


@struct
class nested_t(NamedTuple):
    inner: pair_t
    extra: uint1_t


out_pair: Wire[pair_t]
deep: Wire[nested_t]


@MAIN
def main():
    o = ~i
