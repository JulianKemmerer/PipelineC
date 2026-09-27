# pyright: reportInvalidTypeForm=none
"""Build reproducer for recursively zero-delay wiring-only helpers."""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import AUTO_PIPELINE, MAIN, NamedTuple, hw_func, struct, uint32_t


@struct
class pair_t(NamedTuple):
    a: uint32_t
    b: uint32_t


@hw_func
def swap(p: pair_t) -> pair_t:
    # Both field reads elaborate as generated CONST_REF_RD helpers. The delay
    # walk can skip those children because this whole helper is wiring-only.
    return pair_t(a=p.b, b=p.a)


@hw_func
def core(p: pair_t) -> uint32_t:
    s: pair_t = swap(p)
    return ((s.a + s.b) + s.a) + s.b


CORE = AUTO_PIPELINE(core, latency=2)


@MAIN
def zero_delay_helper_build(a: uint32_t, b: uint32_t) -> uint32_t:
    p: pair_t = pair_t(a=a, b=b)
    return CORE(p)
