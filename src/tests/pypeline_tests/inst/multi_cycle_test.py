# pyright: reportInvalidTypeForm=none
import sys, os

# Path for pypeline import
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

from typing import NamedTuple
from pypeline import (
    MAIN,
    MULTI_CYCLE,
    PART,
    struct,
    Reg,
    uint32_t,
)

# Arty A7-35T — multi-cycle path constraints require Vivado synthesis for now
PART("xc7a35ticsg324-1l")


@struct
class my_struct_t(NamedTuple):
    field: uint32_t


def big_comb_multi_cycle_func(x: my_struct_t) -> my_struct_t:
    rv: my_struct_t
    rv.field = x.field / ~x.field
    return rv


def my_fsm(i: my_struct_t) -> my_struct_t:
    o: my_struct_t
    MC = MULTI_CYCLE[32]
    data0: Reg[my_struct_t, MC.start]
    data1: Reg[my_struct_t, MC.end]
    o = data1
    data1 = big_comb_multi_cycle_func(data0)
    data0 = i
    return o


@MAIN(100.0)
def wrapper(x: my_struct_t) -> my_struct_t:
    rv: my_struct_t
    rv.field = x.field
    for i in range(3):
        f = my_fsm(rv)
        rv.field = rv.field | f.field
    return rv
