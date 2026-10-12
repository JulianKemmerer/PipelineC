# pyright: reportInvalidTypeForm=none
"""Two factory specializations whose only difference is the middle of a
2000-element numpy array argument. They are different hardware: lookup_a adds
1000, lookup_b adds 7. See numpy_factory_arg_identity_test.py."""
import numpy as np

from pypeline import MAIN, hw_func, uint16_t, uint32_t


def make_lookup(table):
    @hw_func
    def lookup(x: uint16_t) -> uint32_t:
        return int(table[1000]) + x

    return lookup


A = np.arange(2000, dtype=np.uint32)
B = A.copy()
B[1000] = 7
lookup_a = make_lookup(A)
lookup_b = make_lookup(B)


@MAIN
def top(x: uint16_t) -> uint32_t:
    return lookup_a(x) + lookup_b(x)
