# pyright: reportInvalidTypeForm=none
"""Top-level synthesis entry point for the AIR7310 PDW project (see README.md).

Only the Pulse Generator (step 1, pulse_gen/pulse_gen.py) is implemented so
far -- the rest of the pipeline (Time-Aligned Detect & Delay Module,
Qualified Storage & PDW Engine) isn't built yet. This wires pulse_gen up
to real top-level ports:

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
`pdw_main` below. `pdw_main` also exposes the detector's bounded pulse
sample stream (Path A gate x Path B delay line, see `detect_pulses.gated_out`)
as a flattened AXI-Stream master output, `rx0_m_axis_*` (RX-side naming, same
tdata packing convention as tx0/rx1) -- `rx0_m_axis_tready` is a real port for
a future consumer to drive but isn't wired to anything internally yet (the
gate stream has no backpressure of its own; see pulse_detect.py's own
"gate_ready" TODO).

As more of the PDW pipeline gets built, this file is where subsequent
stages get wired in and where TX2/host-DMA ports will eventually live.
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
)

from pulse_gen import make_pulse_gen
from pulse_detect import make_detect_pulses

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
# pdw_main -- Path A "TIME-ALIGNED DETECT & DELAY MODULE" front end
# (detect_pulses: magnitude -> dc_block -> moving_avg -> pulse_detect, see
# pulse_detect/pulse_detect.py). Standalone @MAIN; its input sample+valid are
# muxed between the real RX0 ADC input and pulse_gen_main's own generated
# sample+valid (internal loopback) via `pulse_loopback_en` -- only the candidate PDW
# output stream (data + ready) AND the gated pulse sample stream (data/
# valid/last, flattened to rx0_m_axis_*) are exposed as real top-level ports.
# The Qualified Storage & PDW Engine is still out of scope; `overflow` and
# rx0_m_axis_tready's backpressure are computed/declared but left
# unconnected (see pulse_detect.py's own TODOs on both).
# ---------------------------------------------------------------------------
detect_pulses, detect_pulses_t = make_detect_pulses()

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
max_width: Input[uint32_t]

# Loopback select: 1 = feed pdw_main from pulse_gen_main's own generated
# sample (internal, no external cable needed); 0 = feed from the real RX1
# ADC input below. See README.md section 1 "Stimulus & External Loopback".
pulse_loopback_en: Input[uint1_t]

# Candidate PDW output -- the only boundary this task exposes as real ports.
candidate_pdw_valid: Output[uint1_t]
candidate_pdw_pulse_width: Output[uint32_t]
candidate_pdw_peak_power: Output[uint32_t]
candidate_pdw_ready: Input[uint1_t]

# Bounded pulse sample stream (Path A gate x Path B delay line), flattened
# AXI-Stream master -- same tdata packing convention as tx0/rx1 above
# (Q=tdata[31:16], I=tdata[15:0]). Named rx0_ to match rx1_s_axis_tdata's
# RX-side naming (this is the RX1 datapath's own detected-pulse output).
# tready is a real port for a future consumer (DMA/TX2) to drive, but is NOT
# wired to anything internally yet -- gated_sample_t has no backpressure of
# its own (see pulse_detect.py's "gate_ready / backpressure on the gate
# stream" TODO); this is that same still-open TODO, not a new one.
rx0_m_axis_tdata: Output[uint32_t]
rx0_m_axis_tvalid: Output[uint1_t]
rx0_m_axis_tlast: Output[uint1_t]
rx0_m_axis_tready: Input[uint1_t]


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

    o = detect_pulses(
        stream_in_if,
        detect_pulses.out_fb_t(ready=candidate_pdw_ready),
        detect_pulses.power_t(val=threshold_high),
        detect_pulses.power_t(val=threshold_low),
        max_width,
    )

    candidate_pdw_valid = o.pdw_out_if.stream.valid
    candidate_pdw_pulse_width = o.pdw_out_if.stream.data.pulse_width
    candidate_pdw_peak_power = o.pdw_out_if.stream.data.peak_power.val

    gated_i_bits: uint16_t = o.gated_out.data.i.val[15:0]
    gated_q_bits: uint16_t = o.gated_out.data.q.val[15:0]
    rx0_m_axis_tdata = concat(gated_q_bits, gated_i_bits)
    rx0_m_axis_tvalid = o.gated_out.valid
    rx0_m_axis_tlast = o.gated_out.last
