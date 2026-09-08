# pyright: reportInvalidTypeForm=none
"""Two widths of interface-taking broadcast and skid-buffer factories.

Each specialization must retain its own return type and the caller's interface
objects. Reusing a function solely because its interface class is literally
named `stream_intrf` incorrectly binds the eight-byte caller to the four-byte
implementation. This design exercises VHDL emission and synthesis for both.
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

from axi.axis import (
    make_axis_broadcast_interlock,
    make_axis_interface,
    make_axis_skid_buffer,
)

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


skid4, skid4_t = make_axis_skid_buffer(axis4_intrf)
skid8, skid8_t = make_axis_skid_buffer(axis8_intrf)


@MAIN
def skid4_top(
    stream_in_if: axis4_intrf.fwd_t, stream_out_if: axis4_intrf.fb_t
) -> skid4_t:
    return skid4(stream_in_if, stream_out_if)


@MAIN
def skid8_top(
    stream_in_if: axis8_intrf.fwd_t, stream_out_if: axis8_intrf.fb_t
) -> skid8_t:
    return skid8(stream_in_if, stream_out_if)
