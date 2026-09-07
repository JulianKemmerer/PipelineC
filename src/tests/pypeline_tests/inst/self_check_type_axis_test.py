# pyright: reportInvalidTypeForm=none
"""Self-checking @MAIN test: a struct is serialized onto an AXI-Stream by
make_type_to_axis, decoded straight back by make_axis_to_type, and checked
field by field with sim_assert -- no external Python harness.

Registered in native_vs_vhdl_sim_tests.py, which runs the native and
cocotb+GHDL sims and diffs their sim_print(debug=True) output cycle by cycle.
That diff is what makes this test worth more than the native-sim coverage in
type_axis_test.py: the byte-lane muxing, the variable-index buffer writes and
the keep arithmetic all lower to real VHDL here, and native simulation cannot
see a VHDL-only error.

The struct is 7 bytes on a 4-byte bus, so the final beat is partial and the
keep/eod paths -- not just the aligned happy path -- are what get diffed.

Probe rules honoured (see native_vs_vhdl_sim_tests.py's module docstring):
  - every debug print is gated on a real transfer, so VHDL's undefined ('U')
    warm-up registers are never compared against native's typed zeros;
  - no debug print on the sim_finish() cycle.
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
from typing import NamedTuple

from pypeline import (
    MAIN,
    Feedback,
    Reg,
    byte_length,
    sim_assert,
    sim_finish,
    sim_print,
    struct,
    uint1_t,
    uint8_t,
    uint16_t,
    uint32_t,
)

from axi.type_axis import make_axis_to_type, make_type_to_axis

N = 4
NUM_VALUES = 4


@struct
class hdr_t(NamedTuple):
    version: uint8_t
    length: uint16_t
    flags: uint32_t  # 7 bytes: partial final beat on a 4-byte bus


assert byte_length(hdr_t) == 7

tx, tx_t = make_type_to_axis(hdr_t, N)
rx, rx_t = make_axis_to_type(hdr_t, N)


@MAIN
def self_check_type_axis():
    sent: Reg[uint32_t]
    got: Reg[uint32_t]

    # Drive a fresh value each cycle; the serializer's own ready decides when
    # one is actually taken, so this needs no sequencing state of its own.
    v: hdr_t
    v.version = 0xA0 + sent
    v.length = 0x1000 + sent
    # Deliberately under 2**31: sim_print lowers to
    # integer'image(to_integer(x)), and VHDL's `integer` is 32-bit SIGNED, so
    # GHDL raises "overflow detected" at runtime on any uint32_t probe value
    # >= 2**31. (A native-sim-only test would never notice -- which is exactly
    # what this GHDL diff is here to catch.) All four bytes are still
    # non-zero, so the byte-lane muxing is exercised just as well.
    v.flags = 0x7EADBEE0 + sent

    in_stream: tx.in_intrf.stream_t
    in_stream.data.frag = v
    in_stream.data.eod[0] = 1
    in_stream.valid = sent < NUM_VALUES

    # The AXIS beat travels tx -> rx, and rx's ready travels back: a genuine
    # circular reference between two call results, broken with a Feedback on
    # the bare ready bit (an interface half may not be a plain local).
    axis_ready: Feedback[uint1_t]
    tx_o = tx(tx.in_intrf.fwd_t(in_stream), tx.axis_fb_t(axis_ready))
    rx_o = rx(rx.axis_intrf.fwd_t(tx_o.axis_out_if.stream), rx.out_fb_t(1))
    axis_ready = rx_o.axis_in_if.ready

    if in_stream.valid & tx_o.stream_in_if.ready:
        sent = sent + 1

    beat = tx_o.axis_out_if.stream
    if beat.valid & axis_ready:
        # Gated on a real transfer, so no 'U' warm-up value is ever printed.
        sim_print(
            f"beat d0={beat.data.frag.data[0]} d3={beat.data.frag.data[3]} "
            f"k0={beat.data.frag.keep[0]} k3={beat.data.frag.keep[3]} "
            f"eod={beat.data.eod[0]}",
            debug=True,
        )

    recovered = rx_o.stream_out_if.stream
    if recovered.valid:
        sim_assert(
            recovered.data.frag.version == (0xA0 + got),
            f"self_check_type_axis: version mismatch at {got}",
        )
        sim_assert(
            recovered.data.frag.length == (0x1000 + got),
            f"self_check_type_axis: length mismatch at {got}",
        )
        sim_assert(
            recovered.data.frag.flags == (0x7EADBEE0 + got),
            f"self_check_type_axis: flags mismatch at {got}",
        )
        sim_assert(
            recovered.data.eod[0] == 1,
            f"self_check_type_axis: expected eod on value {got}",
        )
        # No debug print on the sim_finish() cycle -- whether a same-cycle VHDL
        # write flushes before std.env.finish is a process-ordering race.
        if got < NUM_VALUES - 1:
            sim_print(
                f"got={got} version={recovered.data.frag.version} flags={recovered.data.frag.flags}",
                debug=True,
            )
        if got == NUM_VALUES - 1:
            sim_finish()
        got = got + 1
