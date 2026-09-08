# pyright: reportInvalidTypeForm=none
"""KNOWN ISSUE reproducer: two instantiations of the same interface-taking
factory, at two different payload widths, in one design.

Expected (broken) behaviour -- VHDL writing aborts with:

    Cant support this assignment in vhdl?
    b8[...]____return_output axis_broadcast_interlock_t_axis_out_if_stream_intrf_data_t_ndarray_fragment_t_frag_5c9a82c6
    DRIVING
    return_output axis_broadcast_interlock_t_axis_out_if_stream_intrf_data_t_ndarray_fragment_t_frag_b32ec8f0

i.e. `b8_t` -- ONE Python class, used both as `b8_top`'s return annotation and
as `b8`'s return type -- resolves to two DIFFERENT canonical struct names, and
`VHDL.py`'s type-resolve then has no conversion between them and `sys.exit(-1)`s.
This is the canonical-name-determinism invariant (a canonical name must be a
pure function of the source) failing for structs whose generated name is long
enough to be collapsed: the two widths' names share every readable token,
because an `@interface` class is always literally named `stream_intrf`
regardless of its payload, and only the appended hash distinguishes them.

`make_axis_broadcast_interlock` is used here deliberately: it is long-standing
library code, so this file is proof the bug is not introduced by whichever
factory happens to trip over it. The same failure hits
`make_axis_skid_buffer` / `make_skid_buffer(some_intrf, ...)`
(`include/pypeline/stream/skid_buffer.py`) and would hit any other factory
taking an `@interface` as an argument.

WORKAROUND, verified: pass the payload TYPE rather than the interface, so the
width lands in the generated names --

    make_skid_buffer(axis_intrf.stream_t.typeof("data"), mode=...)

which builds cleanly at any number of widths in one design. The cost is that
the factory then builds its own interface, so the returned function's
`.stream_intrf` is not the caller's object, and `@interface_func`'s port
matching (which compares interfaces by Python identity) will not pair them.

A single width of any of these factories is completely unaffected -- see
`skid_buffer_test.py`, which builds an AXIS skid buffer and synthesizes fine.
"""
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "..",
        "..",
        "include",
        "pypeline",
    ),
)
from pypeline import MAIN

from axi.axis import make_axis_broadcast_interlock, make_axis_interface

axis4_intrf = make_axis_interface(4)
axis8_intrf = make_axis_interface(8)
bcast4, bcast4_t = make_axis_broadcast_interlock(axis4_intrf, 2)
bcast8, bcast8_t = make_axis_broadcast_interlock(axis8_intrf, 2)


@MAIN
def bcast4_top(
    axis_in_if: axis4_intrf.fwd_t, axis_out_if: axis4_intrf.fb_t[2]
) -> bcast4_t:
    return bcast4(axis_in_if, axis_out_if)


@MAIN
def bcast8_top(
    axis_in_if: axis8_intrf.fwd_t, axis_out_if: axis8_intrf.fb_t[2]
) -> bcast8_t:
    return bcast8(axis_in_if, axis_out_if)
