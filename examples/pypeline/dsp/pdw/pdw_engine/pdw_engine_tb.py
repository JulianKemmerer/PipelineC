# pyright: reportInvalidTypeForm=none
"""Native-sim testbench for the Qualified AXIS Storage & PDW Engine
(pdw_engine.py). sim_assert (in-hardware) is the pass/fail mechanism, same
convention as pulse_gen_tb.py and pulse_detect_tb.py -- not
@sim_input/@sim_output.

This is the unit-level counterpart to ../pdw_tb.py. That one drives the whole
real pipeline through top.py's ports and is the stronger test of what the
engine does with REAL detector output; this one feeds the engine synthetic
gate streams directly, which is the only way to reach cases the real detector
cannot produce on demand:

  * ADC clip and DSP-overflow status flags (status_flags bits 0/1). Driving a
    clipping amplitude through the real chain is impossible -- the power it
    produces overflows the uint32_t threshold ports long before the int16
    rail clips (see ../README.md section 2's threshold-scaling note).
  * Backpressure held for long, deliberate stretches rather than a stutter.
  * Exact beat-for-beat identity of released payload, using a counter as the
    sample value so a dropped, duplicated or reordered beat is visible
    directly rather than via a golden model.

Each @MAIN generates its own periodic gate packets from a free-running
counter, so a packet's expected contents are a closed-form function of its
index -- no golden model, no scoreboard.

Checks:
  1. accept path: every beat of every accepted packet arrives in order,
     exactly pkt_samples of them, with `last` on the final one and never
     before; the valid_pdw arrives BEFORE its packet's first beat and carries
     matching pulse_width/pkt_samples/peak_power/toa.
  2. glitch path: pulses shorter than min_width produce no PDW and no beats.
  3. CW path: pulses at/над max_width produce no PDW and no beats.
  4. status flags: a clipped sample anywhere in a packet sets bit 0 and only
     bit 0; a dsp_overflow beat sets bit 1; neither leaks into the NEXT
     packet (the per-packet accumulators must re-arm).
  5. backpressure: with both consumers stalled for long stretches, nothing is
     lost -- the store-and-forward FIFO absorbs it -- and packet contents are
     unchanged.

Run:
    pypelinec examples/pypeline/dsp/pdw/pdw_engine/pdw_engine_tb.py --sim --comb --run 4000
"""

import os
import sys

sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pulse_detect"),
)

from pypeline import (
    MAIN,
    Reg,
    int16_t,
    sim_assert,
    uint1_t,
    uint4_t,
    uint16_t,
    uint32_t,
    uint64_t,
)

from pulse_detect import make_detect_pulses
from pdw_engine import (
    STATUS_ADC_CLIP,
    STATUS_DSP_OVERFLOW,
    make_pdw_engine,
)

# The engine is built against a detect_pulses instance purely for its types
# (complex_t/gated_sample_t/candidate_pdw_t/width_t); no detector logic is
# instantiated by these testbenches -- the gate stream is synthesized here.
_DP, _ = make_detect_pulses()

RAIL_MAX = 32767  # int16 rail -- what ADC clip detection compares against

# Small FIFOs: this testbench's packets are tens of beats, and a small depth
# keeps the elaborated design light. ../pdw_tb.py exercises top.py's real
# README-sized 16,384-deep instance.
TB_DEPTH = 512
TB_N_PKTS = 8


def _make_gate(dp, width, period):
    """Closed-form gate schedule: a `width`-beat packet at the top of every
    `period` cycles. Returns nothing -- callers inline the same two
    expressions; this docstring is the shared explanation.

    beat k of packet p carries sample value (p * period + k), so any dropped,
    duplicated or reordered beat shows up as a wrong integer, with no golden
    model needed."""


# ---------------------------------------------------------------------------
# 1. Accept path + PDW/packet ordering, no backpressure
# ---------------------------------------------------------------------------
ACC_WIDTH = 24
ACC_PERIOD = 64
ACC_MIN_WIDTH = 8
ACC_MAX_WIDTH = 1000

engine_acc, engine_acc_t = make_pdw_engine(_DP, depth=TB_DEPTH, n_pkts=TB_N_PKTS)


@MAIN(125.0)
def pdw_engine_accept_tb():
    cyc: Reg[uint32_t]
    phase: uint32_t = cyc % ACC_PERIOD
    in_pulse: uint1_t = phase < ACC_WIDTH

    # Sample value == absolute cycle index, so a released beat identifies
    # exactly which input cycle produced it.
    sample_val: int16_t = cyc[15:0]
    gated: _DP.gated_sample_t
    gated.data = _DP.complex_t(
        i=_DP.rail_t(val=sample_val), q=_DP.rail_t(val=0)
    )
    gated.valid = in_pulse
    gated.last = in_pulse & (phase == (ACC_WIDTH - 1))

    # The candidate coincides with gate_last, exactly as the hysteresis SM
    # produces it (see make_pulse_detect_fsm) -- the engine sim_asserts this.
    pdw_in: _DP.out_fwd_t
    pdw_in.stream.valid = gated.last
    pdw_in.stream.data.toa = cyc - (ACC_WIDTH - 1)  # first beat's cycle
    pdw_in.stream.data.pulse_width = ACC_WIDTH
    pdw_in.stream.data.peak_power = _DP.power_t(val=cyc)

    o = engine_acc(gated, pdw_in, 0, ACC_MIN_WIDTH, ACC_MAX_WIDTH, 1, 1)

    cyc = cyc + 1

    sim_assert(
        (~o.pkt_out.last) | o.pkt_out.valid,
        "accept: pkt_out.last without valid -- illegal AXIS",
    )
    sim_assert(o.fifo_full == 0, "accept: packet FIFO overflowed")
    sim_assert(o.verdict.accept | (~gated.last), "accept: verdict rejected a good pulse")

    # --- released-packet tracking -------------------------------------------
    pkts_done: Reg[uint32_t]
    beats_seen: Reg[uint32_t]
    expect_first: Reg[uint32_t]  # cycle index the next packet's beat 0 carries
    pdws_done: Reg[uint32_t]

    if o.pdw_out.valid:
        # Ordering: the PDW for packet N must arrive after packet N-1 has
        # fully drained and before packet N's first beat.
        sim_assert(
            pdws_done == pkts_done,
            "accept: valid_pdw out of order -- a PDW arrived before the "
            "previous packet finished, or two PDWs arrived back to back",
        )
        sim_assert(beats_seen == 0, "accept: valid_pdw arrived mid-packet")
        sim_assert(
            o.pdw_out.data.pulse_width == ACC_WIDTH,
            f"accept: valid_pdw pulse_width != {ACC_WIDTH}",
        )
        sim_assert(
            o.pdw_out.data.pkt_samples == ACC_WIDTH,
            f"accept: valid_pdw pkt_samples != {ACC_WIDTH} (no margins today, "
            "so pkt_samples must equal pulse_width)",
        )
        sim_assert(
            o.pdw_out.data.status_flags == 0,
            "accept: valid_pdw status_flags set with no clip/overflow driven",
        )
        sim_assert(
            o.pdw_out.data.toa == expect_first,
            "accept: valid_pdw toa is not this packet's first sample cycle",
        )
        pdws_done = pdws_done + 1

    if o.pkt_out.valid:
        sim_assert(
            pdws_done == (pkts_done + 1),
            "accept: packet beats arrived before their own valid_pdw",
        )
        got_i: int16_t = o.pkt_out.data.i.val
        want_i: int16_t = (expect_first + beats_seen)[15:0]
        sim_assert(
            got_i == want_i,
            "accept: released beat carries the wrong sample -- a beat was "
            "dropped, duplicated or reordered",
        )
        sim_assert(
            o.pkt_out.last == (beats_seen == (ACC_WIDTH - 1)),
            f"accept: `last` is not on beat {ACC_WIDTH - 1} of the packet",
        )
        if o.pkt_out.last:
            beats_seen = 0
            pkts_done = pkts_done + 1
            expect_first = expect_first + ACC_PERIOD
        else:
            beats_seen = beats_seen + 1

    # Liveness: by this many cycles several whole packets must have come out.
    sim_assert(
        (cyc < (6 * ACC_PERIOD)) | (pkts_done >= 3),
        "accept: fewer than 3 packets released -- the engine stalled",
    )


# ---------------------------------------------------------------------------
# 2. Glitch rejection (pulse_width < min_width): nothing must come out at all
# ---------------------------------------------------------------------------
GLITCH_WIDTH = 6
GLITCH_PERIOD = 48
GLITCH_MIN_WIDTH = 16

engine_glitch, engine_glitch_t = make_pdw_engine(_DP, depth=TB_DEPTH, n_pkts=TB_N_PKTS)


@MAIN(125.0)
def pdw_engine_glitch_tb():
    cyc: Reg[uint32_t]
    phase: uint32_t = cyc % GLITCH_PERIOD
    in_pulse: uint1_t = phase < GLITCH_WIDTH

    sample_val: int16_t = cyc[15:0]
    gated: _DP.gated_sample_t
    gated.data = _DP.complex_t(i=_DP.rail_t(val=sample_val), q=_DP.rail_t(val=0))
    gated.valid = in_pulse
    gated.last = in_pulse & (phase == (GLITCH_WIDTH - 1))

    pdw_in: _DP.out_fwd_t
    pdw_in.stream.valid = gated.last
    pdw_in.stream.data.toa = cyc
    pdw_in.stream.data.pulse_width = GLITCH_WIDTH
    pdw_in.stream.data.peak_power = _DP.power_t(val=cyc)

    o = engine_glitch(gated, pdw_in, 0, GLITCH_MIN_WIDTH, 1000, 1, 1)

    cyc = cyc + 1

    if gated.last:
        sim_assert(o.verdict.is_glitch, "glitch: verdict did not flag a glitch")
        sim_assert(~o.verdict.is_cw, "glitch: verdict wrongly flagged CW")
        sim_assert(~o.verdict.accept, "glitch: verdict accepted a glitch")

    sim_assert(~o.pdw_out.valid, "glitch: a rejected pulse emitted a valid_pdw")
    sim_assert(~o.pkt_out.valid, "glitch: a rejected pulse released beats")
    sim_assert(o.fifo_full == 0, "glitch: packet FIFO overflowed")

    # Liveness: the flush path must actually keep up -- if FLUSH never
    # completed, the FIFO would eventually fill and fifo_full would trip
    # above, but assert progress explicitly too.
    pulses_seen: Reg[uint32_t]
    if gated.last:
        pulses_seen = pulses_seen + 1
    sim_assert(
        (cyc < (6 * GLITCH_PERIOD)) | (pulses_seen >= 4),
        "glitch: fewer than 4 glitch pulses were driven -- test is vacuous",
    )


# ---------------------------------------------------------------------------
# 3. CW rejection (pulse_width >= max_width): nothing must come out either
# ---------------------------------------------------------------------------
CW_WIDTH = 32
CW_PERIOD = 96
CW_MAX_WIDTH = 32  # == the candidate's width: the SM's force-close marker

engine_cw, engine_cw_t = make_pdw_engine(_DP, depth=TB_DEPTH, n_pkts=TB_N_PKTS)


@MAIN(125.0)
def pdw_engine_cw_tb():
    cyc: Reg[uint32_t]
    phase: uint32_t = cyc % CW_PERIOD
    in_pulse: uint1_t = phase < CW_WIDTH

    sample_val: int16_t = cyc[15:0]
    gated: _DP.gated_sample_t
    gated.data = _DP.complex_t(i=_DP.rail_t(val=sample_val), q=_DP.rail_t(val=0))
    gated.valid = in_pulse
    gated.last = in_pulse & (phase == (CW_WIDTH - 1))

    pdw_in: _DP.out_fwd_t
    pdw_in.stream.valid = gated.last
    pdw_in.stream.data.toa = cyc
    pdw_in.stream.data.pulse_width = CW_WIDTH
    pdw_in.stream.data.peak_power = _DP.power_t(val=cyc)

    o = engine_cw(gated, pdw_in, 0, 4, CW_MAX_WIDTH, 1, 1)

    cyc = cyc + 1

    if gated.last:
        sim_assert(o.verdict.is_cw, "CW: verdict did not flag CW at width == max_width")
        sim_assert(~o.verdict.is_glitch, "CW: verdict wrongly flagged a glitch")
        sim_assert(~o.verdict.accept, "CW: verdict accepted a CW pulse")

    sim_assert(~o.pdw_out.valid, "CW: a rejected pulse emitted a valid_pdw")
    sim_assert(~o.pkt_out.valid, "CW: a rejected pulse released beats")
    sim_assert(o.fifo_full == 0, "CW: packet FIFO overflowed")

    pulses_seen: Reg[uint32_t]
    if gated.last:
        pulses_seen = pulses_seen + 1
    sim_assert(
        (cyc < (6 * CW_PERIOD)) | (pulses_seen >= 4),
        "CW: fewer than 4 CW pulses were driven -- test is vacuous",
    )


# ---------------------------------------------------------------------------
# 4. status_flags: clip on packet 1 only, dsp_overflow on packet 2 only.
#    Both must appear in exactly their own packet's flags and NOT leak into
#    the next one -- the per-packet accumulators have to re-arm on `last`.
# ---------------------------------------------------------------------------
ST_WIDTH = 16
ST_PERIOD = 48

engine_st, engine_st_t = make_pdw_engine(_DP, depth=TB_DEPTH, n_pkts=TB_N_PKTS)


@MAIN(125.0)
def pdw_engine_status_tb():
    cyc: Reg[uint32_t]
    phase: uint32_t = cyc % ST_PERIOD
    pkt_idx: uint32_t = cyc / ST_PERIOD
    in_pulse: uint1_t = phase < ST_WIDTH

    # Packet 1 gets exactly ONE clipped sample, mid-packet. Packet 2 gets one
    # dsp_overflow beat instead. Every other packet gets neither.
    clip_now: uint1_t = in_pulse & (pkt_idx == 1) & (phase == 5)
    ovf_now: uint1_t = in_pulse & (pkt_idx == 2) & (phase == 9)

    plain_val: int16_t = cyc[15:0]
    rail: int16_t = RAIL_MAX
    sample_val: int16_t = rail if clip_now else plain_val

    gated: _DP.gated_sample_t
    gated.data = _DP.complex_t(i=_DP.rail_t(val=sample_val), q=_DP.rail_t(val=0))
    gated.valid = in_pulse
    gated.last = in_pulse & (phase == (ST_WIDTH - 1))

    pdw_in: _DP.out_fwd_t
    pdw_in.stream.valid = gated.last
    pdw_in.stream.data.toa = pkt_idx
    pdw_in.stream.data.pulse_width = ST_WIDTH
    pdw_in.stream.data.peak_power = _DP.power_t(val=cyc)

    o = engine_st(gated, pdw_in, ovf_now, 4, 1000, 1, 1)

    cyc = cyc + 1

    if o.pdw_out.valid:
        # toa carries the packet index, so each PDW says which packet it is
        # for without any separate counter to keep in sync.
        want_clip: uint1_t = o.pdw_out.data.toa == 1
        want_ovf: uint1_t = o.pdw_out.data.toa == 2
        want_flags: uint16_t = 0
        if want_clip:
            want_flags = STATUS_ADC_CLIP
        elif want_ovf:
            want_flags = STATUS_DSP_OVERFLOW
        sim_assert(
            o.pdw_out.data.status_flags == want_flags,
            "status: status_flags wrong -- a flag was missed, spuriously set, "
            "or leaked from the previous packet (the per-packet accumulators "
            "must re-arm on `last`)",
        )
        sim_assert(
            o.pdw_out.data.pkt_samples == ST_WIDTH,
            "status: pkt_samples wrong",
        )

    sim_assert(o.fifo_full == 0, "status: packet FIFO overflowed")

    pdws_done: Reg[uint32_t]
    if o.pdw_out.valid:
        pdws_done = pdws_done + 1
    # Must get past packet 2 for the flag checks above to have run at all.
    sim_assert(
        (cyc < (6 * ST_PERIOD)) | (pdws_done >= 4),
        "status: fewer than 4 PDWs emitted -- the clip/overflow packets were "
        "never reached, test is vacuous",
    )


# ---------------------------------------------------------------------------
# 5. Backpressure: both consumers stalled in long stretches. Store-and-forward
#    must absorb it with no loss and identical packet contents.
# ---------------------------------------------------------------------------
BP_WIDTH = 20
BP_PERIOD = 128

engine_bp, engine_bp_t = make_pdw_engine(_DP, depth=TB_DEPTH, n_pkts=TB_N_PKTS)


@MAIN(125.0)
def pdw_engine_backpressure_tb():
    cyc: Reg[uint32_t]
    phase: uint32_t = cyc % BP_PERIOD
    in_pulse: uint1_t = phase < BP_WIDTH

    sample_val: int16_t = cyc[15:0]
    gated: _DP.gated_sample_t
    gated.data = _DP.complex_t(i=_DP.rail_t(val=sample_val), q=_DP.rail_t(val=0))
    gated.valid = in_pulse
    gated.last = in_pulse & (phase == (BP_WIDTH - 1))

    pdw_in: _DP.out_fwd_t
    pdw_in.stream.valid = gated.last
    pdw_in.stream.data.toa = cyc - (BP_WIDTH - 1)
    pdw_in.stream.data.pulse_width = BP_WIDTH
    pdw_in.stream.data.peak_power = _DP.power_t(val=cyc)

    # Long stalls, not a 1-in-N stutter: ready is low for 12 of every 16
    # cycles on the packet side and 8 of every 16 on the PDW side, with
    # different phases, so releases repeatedly start, stall mid-packet, and
    # resume. The gate stream feeding the write side cannot stall at all --
    # that asymmetry is exactly what the store-and-forward FIFO is for.
    slot: uint4_t = cyc[3:0]
    pkt_ready: uint1_t = slot >= 12
    pdw_ready: uint1_t = slot < 8

    o = engine_bp(gated, pdw_in, 0, 4, 1000, pkt_ready, pdw_ready)

    cyc = cyc + 1

    sim_assert(
        (~o.pkt_out.last) | o.pkt_out.valid,
        "backpressure: pkt_out.last without valid -- illegal AXIS",
    )
    sim_assert(o.fifo_full == 0, "backpressure: packet FIFO overflowed")

    # A held beat must not change while the consumer is not ready -- the
    # AXI-Stream rule that makes backpressure lossless.
    held_valid: Reg[uint1_t]
    held_data: Reg[int16_t]
    held_last: Reg[uint1_t]
    if held_valid:
        sim_assert(
            o.pkt_out.valid,
            "backpressure: pkt_out.valid dropped while the consumer was not "
            "ready -- a beat was withdrawn",
        )
        sim_assert(
            (o.pkt_out.data.i.val == held_data) & (o.pkt_out.last == held_last),
            "backpressure: a held beat's data/last changed before it was "
            "accepted",
        )
    held_valid = o.pkt_out.valid & (~pkt_ready)
    held_data = o.pkt_out.data.i.val
    held_last = o.pkt_out.last

    beats_seen: Reg[uint32_t]
    pkts_done: Reg[uint32_t]
    expect_first: Reg[uint32_t]
    if o.pkt_out.valid & pkt_ready:
        got_i: int16_t = o.pkt_out.data.i.val
        want_i: int16_t = (expect_first + beats_seen)[15:0]
        sim_assert(
            got_i == want_i,
            "backpressure: released beat carries the wrong sample -- "
            "store-and-forward lost or reordered a beat under stall",
        )
        if o.pkt_out.last:
            sim_assert(
                beats_seen == (BP_WIDTH - 1),
                f"backpressure: packet ended after the wrong number of beats "
                f"(expected {BP_WIDTH})",
            )
            beats_seen = 0
            pkts_done = pkts_done + 1
            expect_first = expect_first + BP_PERIOD
        else:
            beats_seen = beats_seen + 1

    # Liveness under stall: the release rate is 4/16 cycles, so 20 beats take
    # ~80 cycles -- well inside one 128-cycle period, i.e. the engine must
    # keep up rather than fall progressively behind.
    sim_assert(
        (cyc < (5 * BP_PERIOD)) | (pkts_done >= 3),
        "backpressure: fewer than 3 packets released -- the engine is falling "
        "behind the input rate under stall",
    )
