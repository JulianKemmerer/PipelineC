# pyright: reportInvalidTypeForm=none
from typing import NamedTuple
from pypeline import MAIN, Wire, struct, uint1_t

# Nested/transitive import: file_c is not imported by import_test.py itself, only
# by this file -- proves _process_imports discovers it two hops deep.
import file_c

i: Wire[uint1_t]
o: Wire[uint1_t]


@struct
class pair_t(NamedTuple):
    a: uint1_t
    b: uint1_t
    bits: uint1_t[2]


cfg: Wire[pair_t]


@MAIN
def main():
    o = ~i
    cfg = pair_t(a=i, b=~i, bits=[i, ~i])
    file_c.flag = file_c.bump(i)
