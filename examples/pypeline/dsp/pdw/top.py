# pyright: reportInvalidTypeForm=none
"""Top-level synthesis entry point for the AIR7310 PDW project (see README.md).

All three boxes of the README's architecture are wired up here: the Pulse
Generator (pulse_gen/pulse_gen.py), the Time-Aligned Detect & Delay Module
(pulse_detect/pulse_detect.py), and the Qualified AXIS Storage & PDW Engine
(pdw_engine/pdw_engine.py). What remains unbuilt is inside them, not between
them -- N_pre/N_post margin capture and the TX2 replay fanout; see
README.md's own notes.

pulse_gen_main wires the generator to real top-level ports:

  * flat Input[T] control registers for pri/width/amplitude (as if from
    host config regs -- see README.md section 2), matching how pulse_gen
    is meant to be driven once the rest of the design exists;
  * a flattened AXI-Stream-style master output (tx0_m_axis_tdata/
    tx0_m_axis_tvalid) -- plain uintN_t at the port boundary, not the
    iq_t/stream(iq_t) structs used internally, per the project's
    convention that AXI-Stream is only the top-level interface shape (see
    README.md section 1: "Raw I/Q format"). iq_t's i/q fields are packed
    into tdata per the project-wide convention I = tdata[15:0],
    Q = tdata[31:16]. Named `tx0_` since this drives the first TX port
    (TX1 in the README's diagram, i.e. TX RF Out index 0).

`pdw_main` can consume either the real RX0 ADC input (`rx0_s_axis_tdata`/
`rx0_s_axis_tvalid`) or pulse_gen_main's own generated sample+valid directly
(internal loopback, no external cable needed), selected at runtime by
`pulse_loopback_en` -- see the `pulse_gen_sample`/`pulse_gen_valid` Wires and
`pdw_main` below. It exposes three output boundaries:

  * `candidate_pdw_*` -- Path A's raw, unqualified guess, one per pulse the
    hysteresis SM closes. Observability only, and deliberately kept even
    though the engine downstream is the real consumer: a rejection is only
    visible from outside by seeing a candidate here with no matching
    valid_pdw.
  * `valid_pdw_*` -- README section 4's `valid_pdw_t`, flattened, one per
    ACCEPTED pulse, on a real valid/ready handshake.
  * `rx0_m_axis_*` -- that pulse's released I/Q packet, framed with tlast,
    with `rx0_m_axis_tready` as real backpressure (the store-and-forward FIFO
    is what lets a real-time, un-stallable gate stream feed a consumer that
    can stall).

README section 4 also routes the released packet to TX2 for target replay.
That fanout is not built: a fixed-rate DAC sink cannot drive tready, so
sharing this stream with it needs a policy decision first.
"""

import os
import sys

sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "pulse_gen"),
)
sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "pulse_detect"),
)
sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "pdw_engine"),
)

from pypeline import (
    MAIN,
    PART,
    Input,
    Output,
    Wire,
    concat,
    int16_t,
    uint1_t,
    uint16_t,
    uint32_t,
    uint64_t,
)

from pulse_gen import make_pulse_gen
from pulse_detect import make_detect_pulses
from pdw_engine import make_pdw_engine

PART("xc7a100tcsg324-1")  # Artix-7 100T, same part as board/arty/part100t.py

pulse_gen, out_stream_t = make_pulse_gen()

# Pulse generator control registers (as if from host config regs).
pulse_gen_pri: Input[uint32_t]
pulse_gen_width: Input[uint32_t]
pulse_gen_amplitude: Input[int16_t]

# Flattened AXI-Stream master output, TX1/TX0 (first TX port).
tx0_m_axis_tdata: Output[uint32_t]
tx0_m_axis_tvalid: Output[uint1_t]

# Published by pulse_gen_main, read by pdw_main -- lets pdw_main loop back the
# actual generated sample internally (see pulse_loopback_en below) without
# instantiating a second, independently-counting pulse_gen.
pulse_gen_sample: Wire[pulse_gen.iq_t]
pulse_gen_valid: Wire[uint1_t]


@MAIN(125.0)
def pulse_gen_main():
    o = pulse_gen(pulse_gen_pri, pulse_gen_width, pulse_gen_amplitude)
    # concat() requires unsigned args -- full-width bit-slice reinterprets
    # each int16_t field's raw bits as uint16_t. concat()'s first arg is
    # MSBs, so Q (tdata[31:16]) goes first, I (tdata[15:0]) second, per
    # the project-wide I/Q packing convention.
    i_bits: uint16_t = o.data.i[15:0]
    q_bits: uint16_t = o.data.q[15:0]
    tx0_m_axis_tdata = concat(q_bits, i_bits)
    tx0_m_axis_tvalid = o.valid
    pulse_gen_sample = o.data
    pulse_gen_valid = o.valid


# ---------------------------------------------------------------------------
# pdw_main -- README boxes 2 and 3 end to end:
#   Path A/B "TIME-ALIGNED DETECT & DELAY MODULE" (detect_pulses: magnitude ->
#   dc_block -> moving_avg -> hysteresis SM, plus the Path B delay line, see
#   pulse_detect/pulse_detect.py), feeding
#   "QUALIFIED AXIS STORAGE & PDW ENGINE" (pdw_engine: glitch/CW
#   qualification + store-and-forward release, see pdw_engine/pdw_engine.py).
#
# Standalone @MAIN; its input sample+valid are muxed between the real RX0 ADC
# input and pulse_gen_main's own generated sample+valid (internal loopback)
# via `pulse_loopback_en`.
#
# rx0_m_axis_* carries the QUALIFIED, released packet -- glitches and CW
# events never reach it -- and its tready is real backpressure the
# store-and-forward FIFO absorbs. The raw candidate stream stays exposed
# alongside it (candidate_pdw_*) as a Path A observability tap: every
# candidate appears there, accepted or not, which is what makes a rejection
# visible from outside.
# ---------------------------------------------------------------------------
detect_pulses, detect_pulses_t = make_detect_pulses()
pdw_engine, pdw_engine_t = make_pdw_engine(detect_pulses)

# Raw RX0 ADC input -- flattened AXI-Stream-style slave port, same tdata
# packing convention as pulse_gen_main's tx0 output above (Q=tdata[31:16],
# I=tdata[15:0]). Named rx0_ (first/only RX port), matching rx0_m_axis_*'s
# indexing below and tx0_'s.
rx0_s_axis_tdata: Input[uint32_t]
rx0_s_axis_tvalid: Input[uint1_t]

# Path A config regs (README section 2 host regs). Typed uint32_t at the
# port boundary and cast to detect_pulses.power_t inside pdw_main -- see
# make_detect_pulses' docstring for why that type is NOT a fixed
# make_fixed_t(32, 0) (it's whatever moving_avg's full-precision output
# widens to).
threshold_high: Input[uint32_t]
threshold_low: Input[uint32_t]
# max_width is BOTH Path A's force-close cap (it stops a CW/jamming input
# wedging the hysteresis SM in PULSE forever) and the engine's CW-rejection
# rule, so it feeds both. min_width is the engine's glitch-rejection rule
# only -- Path A has no notion of a minimum. See make_pdw_qualify.
max_width: Input[uint32_t]
min_width: Input[uint32_t]

# Loopback select: 1 = feed pdw_main from pulse_gen_main's own generated
# sample (internal, no external cable needed); 0 = feed from the real RX1
# ADC input below. See README.md section 1 "Stimulus & External Loopback".
pulse_loopback_en: Input[uint1_t]

# Candidate PDW output -- Path A's raw, unqualified guess, every pulse the
# hysteresis SM closes. Observability only (no ready port: the PDW engine is
# the real consumer and is always ready, see make_pdw_engine).
candidate_pdw_valid: Output[uint1_t]
candidate_pdw_toa: Output[uint64_t]
candidate_pdw_pulse_width: Output[uint32_t]
candidate_pdw_peak_power: Output[uint32_t]

# Validated PDW output -- README section 4's valid_pdw_t, flattened, one per
# ACCEPTED pulse, emitted just ahead of that pulse's released packet on
# rx0_m_axis_* below. Real valid/ready handshake to the host.
valid_pdw_valid: Output[uint1_t]
valid_pdw_ready: Input[uint1_t]
valid_pdw_toa: Output[uint64_t]
valid_pdw_pulse_width: Output[uint32_t]
valid_pdw_peak_power: Output[uint32_t]
valid_pdw_pkt_samples: Output[uint32_t]
valid_pdw_status_flags: Output[uint16_t]

# Released pulse packet -- the qualified, store-and-forwarded AXIS master,
# same tdata packing convention as tx0 above (Q=tdata[31:16], I=tdata[15:0]).
# Named rx0_ to match rx0_s_axis_*'s RX-side naming (this is the RX0
# datapath's own detected-pulse output). README section 4 also routes this to
# TX2 for target replay; that fanout is not built (a fixed-rate DAC sink
# cannot drive tready, so it needs its own policy).
rx0_m_axis_tdata: Output[uint32_t]
rx0_m_axis_tvalid: Output[uint1_t]
rx0_m_axis_tlast: Output[uint1_t]
rx0_m_axis_tready: Input[uint1_t]

# Sticky: some packet lost beats to a full store-and-forward FIFO (that
# packet is force-rejected and flagged in its own status_flags bit 2; this
# port is the run-level "it happened at least once" summary).
pkt_fifo_full: Output[uint1_t]


@MAIN(125.0)
def pdw_main():
    # Full-width bit-slice reinterprets raw tdata bits as the declared target
    # type (int16_t here) -- the mirror image of pulse_gen_main's uint16_t reinterpret
    # above (I = tdata[15:0], Q = tdata[31:16]).
    rx0_tdata: uint32_t = rx0_s_axis_tdata
    i_val: int16_t = rx0_tdata[15:0]
    q_val: int16_t = rx0_tdata[31:16]
    rx_sample: detect_pulses.complex_t = detect_pulses.complex_t(
        i=detect_pulses.rail_t(val=i_val), q=detect_pulses.rail_t(val=q_val)
    )
    # Internal loopback: bypass the external TX1->cable->RX0 path and use
    # pulse_gen_main's own generated sample directly (see pulse_gen_sample
    # Wire above).
    loopback_sample: detect_pulses.complex_t = detect_pulses.complex_t(
        i=detect_pulses.rail_t(val=pulse_gen_sample.i),
        q=detect_pulses.rail_t(val=pulse_gen_sample.q),
    )
    sample: detect_pulses.complex_t = (
        loopback_sample if pulse_loopback_en else rx_sample
    )
    sample_valid: uint1_t = (
        pulse_gen_valid if pulse_loopback_en else rx0_s_axis_tvalid
    )
    stream_in_if: detect_pulses.in_stream_t = detect_pulses.in_stream_t(
        sample, sample_valid
    )

    # The engine's candidate-stream ready is a constant 1 (see
    # make_pdw_engine), so it can be fed in directly here rather than routed
    # back out of `e` -- there is no combinational loop to break.
    o = detect_pulses(
        stream_in_if,
        detect_pulses.out_fb_t(1),
        detect_pulses.power_t(val=threshold_high),
        detect_pulses.power_t(val=threshold_low),
        max_width,
    )

    candidate_pdw_valid = o.pdw_out_if.stream.valid
    candidate_pdw_toa = o.pdw_out_if.stream.data.toa
    candidate_pdw_pulse_width = o.pdw_out_if.stream.data.pulse_width
    candidate_pdw_peak_power = o.pdw_out_if.stream.data.peak_power.val

    e = pdw_engine(
        o.gated_out,
        o.pdw_out_if,
        o.overflow,
        min_width,
        max_width,
        rx0_m_axis_tready,
        valid_pdw_ready,
    )

    valid_pdw_valid = e.pdw_out.valid
    valid_pdw_toa = e.pdw_out.data.toa
    valid_pdw_pulse_width = e.pdw_out.data.pulse_width
    valid_pdw_peak_power = e.pdw_out.data.peak_power
    valid_pdw_pkt_samples = e.pdw_out.data.pkt_samples
    valid_pdw_status_flags = e.pdw_out.data.status_flags

    gated_i_bits: uint16_t = e.pkt_out.data.i.val[15:0]
    gated_q_bits: uint16_t = e.pkt_out.data.q.val[15:0]
    rx0_m_axis_tdata = concat(gated_q_bits, gated_i_bits)
    rx0_m_axis_tvalid = e.pkt_out.valid
    rx0_m_axis_tlast = e.pkt_out.last

    pkt_fifo_full = e.fifo_full
