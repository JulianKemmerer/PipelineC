# pyright: reportInvalidTypeForm=none
from pypeline import MAIN, Wire, uint1_t

i: Wire[uint1_t]
o: Wire[uint1_t]


@MAIN
def main_a():
    o = ~i
