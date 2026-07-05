# pyright: reportInvalidTypeForm=none
from pypeline import hw_func, uint1_t

import importfrom_leaf


def make_mid_wrapper():
    @hw_func
    def mid_wrapper(x: uint1_t) -> uint1_t:
        return importfrom_leaf.leaf_func(x)

    return mid_wrapper
