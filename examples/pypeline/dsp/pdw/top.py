# pyright: reportInvalidTypeForm=none
"""Top-level synthesis entry point for the AIR7310 PDW project (see README.md).

All of the README's architecture is wired up here: the control register file
(pdw_ctrl/pdw_ctrl.py), the Pulse Generator (pulse_gen/pulse_gen.py), the
Time-Aligned Detect & Delay Module (pulse_detect/pulse_detect.py), the per-pulse
measurement engine (pdw_measure/pdw_measure.py), and the Qualified AXIS Storage
& PDW Engine (pdw_engine/pdw_engine.py). What remains unbuilt is inside them,
not between them -- N_pre/N_post margin capture; see README.md's own notes.

EVERY top-level port is a flattened 32-bit AXI-Stream. Nothing here is a wide
parallel register bus any more: control arrives as a framed struct, PDW records
and candidate records leave as framed structs, and the released pulse packet is
broadcast to two masters. Interface types (`axis32_intrf`, the serializers'
own) live inside; the boundary is plain `uintN_t`, per the project's convention
that AXI-Stream is only the top-level interface shape.

  rx0_s_axis_*  in   ADC I/Q samples, one sample per beat
  tx0_s_axis_*  in   pdw_ctrl_t control-register struct (ten beats)
  rx0_m_axis_*  out  released pulse packet          (broadcast leg 0)
  rx1_m_axis_*  out  valid_pdw_t records (ten beats)
  rx2_m_axis_*  out  candidate_rec_t records (four beats), observability
  tx0_m_axis_*  out  pulse_gen stimulus, for the TX->cable->RX0 loopback
  tx1_m_axis_*  out  released pulse packet          (broadcast leg 1, replay)

I/Q packing on every sample-carrying port is the project-wide convention
I = tdata[15:0], Q = tdata[31:16].

This file is also the ONLY place several critical paths exist. The generator's
output feeds the detector's magnitude multiplier, the detector's phasor
accumulators feed the measurement CORDIC, and now the two masters' tready pins
feed the store-and-forward FSM through the broadcast interlock -- all in the
same clock domain, all across a module boundary. Each block met its 125 MHz
target on its own while the composed design ran at 63 MHz; see README.md's
synthesis table. That is why `top.py` is registered as its own synthesis test
rather than treated as covered by the block-level ones.
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
sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "pdw_ctrl"),
)

from pypeline import (
    MAIN,
    PART,
    Feedback,
    Input,
    NamedTuple,
    Output,
    Wire,
    array_to_uint_le,
    concat,
    int16_t,
    make_uint_t,
    struct,
    uint1_t,
    uint16_t,
    uint32_t,
    uint64_t,
    uint_to_array_le,
)

from axi.axis import make_axis_broadcast_interlock, make_axis_interface
from axi.type_axis import make_type_to_axis

from pdw_ctrl import CTRL_FLAG_LOOPBACK_EN, make_pdw_ctrl, pdw_ctrl_t
from pulse_gen import make_pulse_gen
from pulse_detect import make_detect_pulses
from pdw_engine import make_pdw_engine

PART("xc7a100tcsg324-1")  # Artix-7 100T, same part as board/arty/part100t.py

# One bus width for every port: 4 byte lanes = 32 bits.
AXIS_N = 4
tkeep_t = make_uint_t(AXIS_N)
KEEP_ALL = (1 << AXIS_N) - 1
axis32_intrf = make_axis_interface(AXIS_N)

pulse_gen, out_stream_t = make_pulse_gen()
pdw_ctrl, pdw_ctrl_out_t = make_pdw_ctrl(AXIS_N)

# ---------------------------------------------------------------------------
# ctrl_main -- the control register file (README section 2).
#
# Its own @MAIN rather than a block inside pdw_main, because both other MAINs
# consume it: pulse_gen_main needs the stimulus settings and pdw_main needs the
# detector/engine ones. The live values are published on a Wire, exactly as
# pulse_gen_main publishes its generated sample below.
# ---------------------------------------------------------------------------
tx0_s_axis_tdata: Input[uint32_t]
tx0_s_axis_tkeep: Input[tkeep_t]
tx0_s_axis_tlast: Input[uint1_t]
tx0_s_axis_tvalid: Input[uint1_t]
tx0_s_axis_tready: Output[uint1_t]

# Live control-register values, written by ctrl_main and read by both other
# MAINs. Holds pdw_ctrl.defaults until the first well-formed frame arrives.
ctrl_regs: Wire[pdw_ctrl_t]


@MAIN(125.0)
def ctrl_main():
    # Typed locals first: uint_to_array_le splits by the value's WIDTH, and a
    # port read straight into it carries only whatever width its current value
    # implies (a plain int in native sim). Naming the type pins it at 32/4 bits
    # -- the same reason pdw_main reads `rx0_tdata: uint32_t` before slicing.
    ctrl_tdata: uint32_t = tx0_s_axis_tdata
    ctrl_tkeep: tkeep_t = tx0_s_axis_tkeep
    ci: pdw_ctrl.axis_intrf.stream_t
    ci.data.frag.data = uint_to_array_le(ctrl_tdata, 8)
    ci.data.frag.keep = uint_to_array_le(ctrl_tkeep, 1)
    ci.data.eod[0] = tx0_s_axis_tlast
    ci.valid = tx0_s_axis_tvalid

    c = pdw_ctrl(pdw_ctrl.axis_intrf.fwd_t(ci))
    tx0_s_axis_tready = c.axis_in_if.ready
    ctrl_regs = c.regs


# ---------------------------------------------------------------------------
# pulse_gen_main -- the stimulus (README section 1).
# ---------------------------------------------------------------------------

# Flattened AXI-Stream master output for the generated stimulus, TX0. Driving a
# DAC with this and cabling it back into RX0 is the external loopback path;
# `pulse_loopback_en` in the control struct is the internal shortcut.
tx0_m_axis_tdata: Output[uint32_t]
tx0_m_axis_tkeep: Output[tkeep_t]
tx0_m_axis_tlast: Output[uint1_t]
tx0_m_axis_tvalid: Output[uint1_t]
# NOT CONNECTED: a fixed-rate DAC cannot back-pressure a fixed-rate generator,
# so this input is accepted and ignored. The port exists for interface
# uniformity; the generator free-runs regardless of what is driven here.
tx0_m_axis_tready: Input[uint1_t]

# Published by pulse_gen_main, read by pdw_main -- lets pdw_main loop back the
# actual generated sample internally (see CTRL_FLAG_LOOPBACK_EN) without
# instantiating a second, independently-counting pulse_gen.
pulse_gen_sample: Wire[pulse_gen.iq_t]
pulse_gen_valid: Wire[uint1_t]


@MAIN(125.0)
def pulse_gen_main():
    o = pulse_gen(
        ctrl_regs.pulse_gen_pri,
        ctrl_regs.pulse_gen_width,
        ctrl_regs.pulse_gen_amplitude,
        ctrl_regs.pulse_gen_freq,
        ctrl_regs.pulse_gen_chirp_rate,
        ctrl_regs.pulse_gen_noise_amp,
    )
    # concat() requires unsigned args -- full-width bit-slice reinterprets
    # each int16_t field's raw bits as uint16_t. concat()'s first arg is
    # MSBs, so Q (tdata[31:16]) goes first, I (tdata[15:0]) second.
    i_bits: uint16_t = o.data.i[15:0]
    q_bits: uint16_t = o.data.q[15:0]
    tx0_m_axis_tdata = concat(q_bits, i_bits)
    tx0_m_axis_tvalid = o.valid
    # Every beat is one whole sample, and the stimulus is a continuous
    # unframed stream -- so keep is constant and tlast never asserts.
    tx0_m_axis_tkeep = KEEP_ALL
    tx0_m_axis_tlast = 0
    pulse_gen_sample = o.data
    pulse_gen_valid = o.valid


# ---------------------------------------------------------------------------
# pdw_main -- README boxes 2 and 3 end to end:
#   Path A/B "TIME-ALIGNED DETECT & DELAY MODULE" (detect_pulses: magnitude ->
#   dc_block -> moving_avg -> hysteresis SM, plus the Path B delay line), feeding
#   "QUALIFIED AXIS STORAGE & PDW ENGINE" (pdw_engine: glitch/CW qualification
#   + store-and-forward release), feeding three AXIS masters.
#
# Its input sample+valid are muxed between the real RX0 ADC input and
# pulse_gen_main's own generated sample (internal loopback) via the control
# struct's CTRL_FLAG_LOOPBACK_EN.
# ---------------------------------------------------------------------------
detect_pulses, detect_pulses_t = make_detect_pulses()
pdw_engine, pdw_engine_t = make_pdw_engine(detect_pulses)


@struct
class candidate_rec_t(NamedTuple):
    """Port-facing form of Path A's `candidate_pdw_t` -- 16 bytes, four beats.

    NOT `candidate_pdw_t` itself: its `peak_power` is `power_t`, 46 bits, which
    would make an 18-byte record with a ragged final beat. Truncating to
    uint32_t is exactly what `valid_pdw_t.peak_power` already does, so the two
    observability views of the same pulse report the same number."""

    toa: uint64_t  # 64
    pulse_width: uint32_t  # 32
    peak_power: uint32_t  # 32   linear, power_t truncated


pdw_tx, _pdw_tx_t = make_type_to_axis(pdw_engine.valid_pdw_t, AXIS_N)
cand_tx, _cand_tx_t = make_type_to_axis(candidate_rec_t, AXIS_N)
# Two sinks for the released packet: the host capture port and the TX replay
# port. Combinational valid/ready interlocking, no buffering -- see
# make_axis_broadcast_interlock.
pkt_bcast, _pkt_bcast_t = make_axis_broadcast_interlock(axis32_intrf, 2)

# Raw RX0 ADC input.
rx0_s_axis_tdata: Input[uint32_t]
rx0_s_axis_tvalid: Input[uint1_t]
# NOT CONNECTED: a sample beat is always four real bytes, and the ADC stream is
# continuous and unframed, so neither of these carries information here.
rx0_s_axis_tkeep: Input[tkeep_t]
rx0_s_axis_tlast: Input[uint1_t]
# DRIVEN CONSTANT 1: an ADC cannot be back-pressured. Ready propagates backwards
# from the masters as far as the store-and-forward FIFO and stops there -- when
# that FIFO fills, beats are dropped and the affected packet is flagged in-band
# with status_flags bit 2 (STATUS_PKT_FIFO_FULL). This port exists for interface
# uniformity; see README.md's backpressure notes.
rx0_s_axis_tready: Output[uint1_t]

# Released pulse packet, leg 0: the qualified, store-and-forwarded capture
# stream to the host. tlast frames each pulse's packet.
rx0_m_axis_tdata: Output[uint32_t]
rx0_m_axis_tkeep: Output[tkeep_t]
rx0_m_axis_tlast: Output[uint1_t]
rx0_m_axis_tvalid: Output[uint1_t]
rx0_m_axis_tready: Input[uint1_t]

# Released pulse packet, leg 1: README section 4's TX2 target replay.
# ⚠ TIE THIS READY HIGH IF THE REPLAY PORT IS UNUSED. The broadcast interlock
# ANDs both legs' ready together, so a leg held low wedges the release path for
# the host capture port as well.
tx1_m_axis_tdata: Output[uint32_t]
tx1_m_axis_tkeep: Output[tkeep_t]
tx1_m_axis_tlast: Output[uint1_t]
tx1_m_axis_tvalid: Output[uint1_t]
tx1_m_axis_tready: Input[uint1_t]

# Validated PDW output -- README section 4's valid_pdw_t, one 40-byte frame per
# ACCEPTED pulse, emitted just ahead of that pulse's released packet. Real
# backpressure: the engine's EMIT_PDW state holds until this drains.
# `gr_pdw_record.py` parses these bytes directly.
rx1_m_axis_tdata: Output[uint32_t]
rx1_m_axis_tkeep: Output[tkeep_t]
rx1_m_axis_tlast: Output[uint1_t]
rx1_m_axis_tvalid: Output[uint1_t]
rx1_m_axis_tready: Input[uint1_t]

# Candidate PDW output -- Path A's raw, unqualified guess, one 16-byte frame per
# pulse the hysteresis SM closes, accepted or not. Observability only: seeing a
# candidate here with no matching valid_pdw is what makes a rejection visible
# from outside.
#
# tready is fully functional -- the serializer honours it and holds mid-frame --
# but it does NOT propagate back into Path A, which is real-time and cannot
# stall. A candidate arriving while the serializer is still busy is dropped
# silently. In a real system this port is expected to be tied ready=1 and
# ignored; pdw_tb.py stalls it anyway so the path stays real.
rx2_m_axis_tdata: Output[uint32_t]
rx2_m_axis_tkeep: Output[tkeep_t]
rx2_m_axis_tlast: Output[uint1_t]
rx2_m_axis_tvalid: Output[uint1_t]
rx2_m_axis_tready: Input[uint1_t]


@MAIN(125.0)
def pdw_main():
    # Both readies are consumed by pdw_engine and produced from its own outputs
    # -- a genuine circular reference between two call results, which is what
    # Feedback[T] is for (same shape as type_axis.py's ready_for_limiter).
    pkt_ready: Feedback[uint1_t]
    pdw_ready: Feedback[uint1_t]

    # Full-width bit-slice reinterprets raw tdata bits as the declared target
    # type (int16_t here) -- the mirror image of pulse_gen_main's uint16_t
    # reinterpret above (I = tdata[15:0], Q = tdata[31:16]).
    rx0_tdata: uint32_t = rx0_s_axis_tdata
    i_val: int16_t = rx0_tdata[15:0]
    q_val: int16_t = rx0_tdata[31:16]
    rx_sample: detect_pulses.complex_t = detect_pulses.complex_t(
        i=detect_pulses.rail_t(val=i_val), q=detect_pulses.rail_t(val=q_val)
    )
    # Internal loopback: bypass the external TX0->cable->RX0 path and use
    # pulse_gen_main's own generated sample directly.
    loopback_sample: detect_pulses.complex_t = detect_pulses.complex_t(
        i=detect_pulses.rail_t(val=pulse_gen_sample.i),
        q=detect_pulses.rail_t(val=pulse_gen_sample.q),
    )
    lb_mask: uint32_t = CTRL_FLAG_LOOPBACK_EN
    loopback_en: uint1_t = (ctrl_regs.flags & lb_mask) != 0
    sample: detect_pulses.complex_t = (
        loopback_sample if loopback_en else rx_sample
    )
    sample_valid: uint1_t = (
        pulse_gen_valid if loopback_en else rx0_s_axis_tvalid
    )
    stream_in_if: detect_pulses.in_stream_t = detect_pulses.in_stream_t(
        sample, sample_valid
    )
    rx0_s_axis_tready = 1  # see the port declaration

    # The engine's candidate-stream ready is a constant 1 (see
    # make_pdw_engine), so it can be fed in directly here rather than routed
    # back out of `e` -- there is no combinational loop to break.
    o = detect_pulses(
        stream_in_if,
        detect_pulses.out_fb_t(1),
        detect_pulses.power_t(val=ctrl_regs.threshold_high),
        detect_pulses.power_t(val=ctrl_regs.threshold_low),
        ctrl_regs.max_width,
    )

    e = pdw_engine(
        o.gated_out,
        o.pdw_out_if,
        o.overflow,
        ctrl_regs.min_width,
        ctrl_regs.max_width,
        o.freq_acc,
        o.noise_est,
        pkt_ready,
        pdw_ready,
    )

    # -- released packet -> broadcast -> rx0_m (host) and tx1_m (replay) -----
    # One sample is exactly one 4-byte beat, so this is a repack, not a
    # serializer: no extra latency and no change in throughput.
    gated_i_bits: uint16_t = e.pkt_out.data.i.val[15:0]
    gated_q_bits: uint16_t = e.pkt_out.data.q.val[15:0]
    keep_all: tkeep_t = KEEP_ALL
    pkt_tdata: uint32_t = concat(gated_q_bits, gated_i_bits)
    pk: axis32_intrf.stream_t
    pk.data.frag.data = uint_to_array_le(pkt_tdata, 8)
    pk.data.frag.keep = uint_to_array_le(keep_all, 1)
    pk.data.eod[0] = e.pkt_out.last
    pk.valid = e.pkt_out.valid
    b = pkt_bcast(
        axis32_intrf.fwd_t(pk),
        [
            axis32_intrf.fb_t(rx0_m_axis_tready),
            axis32_intrf.fb_t(tx1_m_axis_tready),
        ],
    )
    pkt_ready = b.axis_in_if.ready

    rx0_m_axis_tdata = array_to_uint_le(b.axis_out_if[0].stream.data.frag.data)
    rx0_m_axis_tkeep = array_to_uint_le(b.axis_out_if[0].stream.data.frag.keep)
    rx0_m_axis_tlast = b.axis_out_if[0].stream.data.eod[0]
    rx0_m_axis_tvalid = b.axis_out_if[0].stream.valid
    tx1_m_axis_tdata = array_to_uint_le(b.axis_out_if[1].stream.data.frag.data)
    tx1_m_axis_tkeep = array_to_uint_le(b.axis_out_if[1].stream.data.frag.keep)
    tx1_m_axis_tlast = b.axis_out_if[1].stream.data.eod[0]
    tx1_m_axis_tvalid = b.axis_out_if[1].stream.valid

    # -- valid_pdw_t -> rx1_m ------------------------------------------------
    vs: pdw_tx.in_intrf.stream_t
    vs.data.frag = e.pdw_out.data
    vs.data.eod[0] = 1  # one record per frame
    vs.valid = e.pdw_out.valid
    vt = pdw_tx(pdw_tx.in_intrf.fwd_t(vs), pdw_tx.axis_fb_t(rx1_m_axis_tready))
    pdw_ready = vt.stream_in_if.ready

    rx1_m_axis_tdata = array_to_uint_le(vt.axis_out_if.stream.data.frag.data)
    rx1_m_axis_tkeep = array_to_uint_le(vt.axis_out_if.stream.data.frag.keep)
    rx1_m_axis_tlast = vt.axis_out_if.stream.data.eod[0]
    rx1_m_axis_tvalid = vt.axis_out_if.stream.valid

    # -- candidate_pdw_t -> rx2_m -------------------------------------------
    # `ct.stream_in_if.ready` is deliberately NOT fed back anywhere: Path A is
    # real-time and unstallable, so a candidate offered while the serializer is
    # busy is simply lost. See the port declaration.
    cand: candidate_rec_t = candidate_rec_t(
        toa=o.pdw_out_if.stream.data.toa,
        pulse_width=o.pdw_out_if.stream.data.pulse_width,
        peak_power=o.pdw_out_if.stream.data.peak_power.val,
    )
    cs: cand_tx.in_intrf.stream_t
    cs.data.frag = cand
    cs.data.eod[0] = 1
    cs.valid = o.pdw_out_if.stream.valid
    ct = cand_tx(cand_tx.in_intrf.fwd_t(cs), cand_tx.axis_fb_t(rx2_m_axis_tready))

    rx2_m_axis_tdata = array_to_uint_le(ct.axis_out_if.stream.data.frag.data)
    rx2_m_axis_tkeep = array_to_uint_le(ct.axis_out_if.stream.data.frag.keep)
    rx2_m_axis_tlast = ct.axis_out_if.stream.data.eod[0]
    rx2_m_axis_tvalid = ct.axis_out_if.stream.valid
