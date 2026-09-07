# pyright: reportInvalidTypeForm=none
"""Standalone synthesis check for the struct<->AXIS blocks.

`make_axis_to_type`/`make_type_to_axis` produce submodules with no top-level
ports of their own -- they are meant to be called from inside a larger design.
This file gives them real chip-boundary ports so they can be elaborated and
synthesized in isolation, following the `*_synth_top.py` convention used by
examples/pypeline/dsp/pdw/. Native simulation never emits VHDL, so this is what
catches the VHDL-only error class (reserved words, mismatched operand widths)
for this layer.

The struct is deliberately 13 bytes on a 4-byte bus: not a multiple, so the
partial-beat/keep paths are the ones synthesized, not just the easy aligned
case. It carries no tests -- type_axis_test.py has those.
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
from enum import auto
from typing import NamedTuple

from pypeline import (
    MAIN,
    PypelineEnum,
    byte_length,
    enum,
    struct,
    uint8_t,
    uint16_t,
    uint32_t,
    uint64_t,
)

from axi.type_axis import make_axis_to_type, make_type_to_axis

N = 4


@enum
class link_state_t(PypelineEnum):
    DOWN = auto()
    TRAINING = auto()
    UP = auto()


@struct
class record_t(NamedTuple):
    state: link_state_t  # 2 bits -> 1 byte
    seq: uint16_t  # 2
    stamp: uint64_t  # 8
    crc: uint16_t  # 2
    # 13 bytes total: 3 full beats + a 1-byte partial beat on a 4-byte bus


assert byte_length(record_t) == 13, byte_length(record_t)

rx, rx_t = make_axis_to_type(record_t, N)
tx, tx_t = make_type_to_axis(record_t, N)
rx_many, rx_many_t = make_axis_to_type(record_t, N, frame="many_per_packet")
tx_many, tx_many_t = make_type_to_axis(
    record_t, N, frame="many_per_packet", structs_per_packet=4
)


@MAIN
def axis_to_record(
    axis_in_if: rx.axis_intrf.fwd_t, stream_out_if: rx.out_fb_t
) -> rx_t:
    return rx(axis_in_if, stream_out_if)


@MAIN
def record_to_axis(
    stream_in_if: tx.in_intrf.fwd_t, axis_out_if: tx.axis_fb_t
) -> tx_t:
    return tx(stream_in_if, axis_out_if)


@MAIN
def axis_to_record_many(
    axis_in_if: rx_many.axis_intrf.fwd_t, stream_out_if: rx_many.out_fb_t
) -> rx_many_t:
    return rx_many(axis_in_if, stream_out_if)


@MAIN
def record_to_axis_many(
    stream_in_if: tx_many.in_intrf.fwd_t, axis_out_if: tx_many.axis_fb_t
) -> tx_many_t:
    return tx_many(stream_in_if, axis_out_if)
