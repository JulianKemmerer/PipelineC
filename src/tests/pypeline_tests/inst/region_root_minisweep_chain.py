# pyright: reportInvalidTypeForm=none
"""Chain module of region_root_minisweep_design.py: `chain` runs six imported
steps, and `chain_wrapper` is the one-line wrapper designs used to write so the
sweep could find and mini-sweep `chain` inside its region (#387)."""
from pypeline import hw_func

from region_root_minisweep_math import st4_t, step


@hw_func
def chain(s: st4_t) -> st4_t:
    a = step(s)
    b = step(a)
    c = step(b)
    d = step(c)
    e = step(d)
    f = step(e)
    return f


@hw_func
def chain_wrapper(s: st4_t) -> st4_t:
    return chain(s)
