# pyright: reportInvalidTypeForm=none
import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "def")
)

from pypeline import MAIN

import file_a
import file_b


@MAIN
def a_b_connect():
    file_b.i = file_a.o
    file_a.i = file_b.o
    # Nested cross-module field reads/writes: module.wire.field / module.wire.field[i].
    # Previously KeyError'd in _elab_ref_read/_elab_assign ('file_a'/'file_b' treated
    # as ordinary local base tokens instead of module aliases).
    file_b.out_pair.a = file_a.cfg.a
    file_b.out_pair.b = file_a.cfg.bits[0]
    file_b.out_pair.bits[0] = file_a.cfg.bits[1]
    file_b.out_pair.bits[1] = file_a.cfg.b
    # Nested cross-module struct-constructor-call write: exercises the
    # compound-init generic fallback for a >2-token target.
    file_b.deep.inner = file_b.pair_t(
        a=file_a.cfg.a,
        b=file_a.cfg.b,
        bits=[file_a.cfg.bits[0], file_a.cfg.bits[1]],
    )
    file_b.deep.extra = file_a.cfg.a
