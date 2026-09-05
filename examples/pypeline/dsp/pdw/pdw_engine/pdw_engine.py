# pyright: reportInvalidTypeForm=none
"""QUALIFIED AXIS STORAGE & PDW ENGINE -- the README's box 3, the gatekeeper
between Path A/B's raw candidate stream and the outside world.

It takes the two things the Time-Aligned Detect & Delay Module produces --
a real-time `gated_sample_t` beat stream (time-aligned raw I/Q, framed by the
hysteresis SM's gate) and a `candidate_pdw_t` per completed pulse -- and:

  1. Stores every gate beat in a store-and-forward FIFO as it arrives.
  2. Qualifies the candidate against the host's rules when the pulse ends
     (glitch: pulse_width < min_width; CW: pulse_width >= max_width).
  3. Executes: a qualified pulse gets its metadata upgraded to a
     `valid_pdw_t` and emitted, followed by its buffered AXIS packet framed
     with `last`; a rejected pulse is erased -- no PDW, no beats, the
     buffered samples silently dropped.

WHY A DESCRIPTOR FIFO INSTEAD OF A ROLLBACK POINTER
The README describes step 3's reject path as "Rollback/Flush FIFO", which
suggests rewinding a write pointer. That is not available: `make_fifo`
(include/pypeline/fifo.py) is a black-box wrapper over
src/vhdl/pipelinec_fifo_fwft.vhd exposing only push/pop -- no pointers, no
occupancy, no commit/drop (the upstream axis_fifo.v this was derived from has
FRAME_FIFO/DROP_BAD_FRAME logic, but it was stripped out; restoring it is a
possible future optimisation). There is no RAM primitive in the Pypeline
library either.

So the equivalent behaviour is built from two plain FIFOs plus a counter:

  * a DATA FIFO holding every beat, and
  * a DESCRIPTOR FIFO holding one entry per completed pulse: the finished
    `valid_pdw_t` plus an accept/reject bit.

The read side pops a descriptor, then moves exactly `pkt_samples` beats --
downstream if accepted, into the bit bucket if not. The observable result is
identical to a rollback (a rejected pulse is completely erased), at the cost
of spending read bandwidth to discard. That is affordable here because the
hysteresis SM cannot emit gate beats and a stale packet's discard at the same
time for long: a glitch is by definition shorter than `min_width`, and a CW
event parks the SM in RECOVER (no beats at all) while its `max_width` beats
drain.

Counting beats that were actually PUSHED, rather than trusting the
candidate's `pulse_width`, is what makes the read side robust: if the data
FIFO ever did fill and drop beats, the flush count still matches what is
really in the FIFO, so one corrupt packet cannot desynchronize every packet
after it. (That packet is force-rejected anyway, and reported via
status_flags bit 2.)

NOT IMPLEMENTED HERE -- N_pre/N_post margins. The README's
`pkt_samples = N_pre + width + N_post`; today the gate window is the whole
packet, so `pkt_samples == pulse_width` for every accepted pulse. Margins
need the Path B delay line deepened by N_pre and the gate held open past
gate_last, and belong to a later increment.
"""

from enum import IntEnum

from pypeline import (
    NamedTuple,
    Reg,
    enum,
    hw_func,
    sim_assert,
    struct,
    uint1_t,
    uint16_t,
    uint32_t,
    uint64_t,
)

from fifo import make_fifo
from dsp.fir_common import data_range

# README section 4's status_flags bitfield.
STATUS_ADC_CLIP = 1 << 0
STATUS_DSP_OVERFLOW = 1 << 1
STATUS_PKT_FIFO_FULL = 1 << 2

# README section 4: valid_pdw_t is 192 bits / 24 bytes, so peak_power is a
# uint32_t regardless of how wide the detector's internal power_t is. See
# make_pdw_engine for the truncation that implies.
PEAK_POWER_BITS = 32


def make_pdw_qualify(width_t=uint32_t):
    """Post-pulse qualification (README box 3 step 2). Returns
    (pdw_qualify, verdict_t). Pure combinational -- one compare each.

        pdw_qualify(pulse_width, min_width, max_width) -> verdict_t
        verdict_t{accept, is_glitch, is_cw}

    Glitch rejection is `pulse_width < min_width`, straight from the README.

    CW rejection is `pulse_width >= max_width`, NOT the README's literal
    `> max_width`: the hysteresis SM force-terminates a runaway pulse the
    moment its width reaches max_width and emits exactly one candidate of
    that width (see make_pulse_detect_fsm's docstring on why RECOVER exists),
    so `== max_width` IS the CW marker and a strict `>` would never fire. The
    `>=` form also covers a hypothetical wider candidate.

    A consequence worth stating: `max_width` is a real detection limit, not
    just a rejection threshold. A genuine pulse longer than max_width is
    reported as CW and discarded, exactly as an unbounded-duration jammer
    would be -- the two are indistinguishable to this design.
    """

    @struct
    class verdict_t(NamedTuple):
        accept: uint1_t
        is_glitch: uint1_t
        is_cw: uint1_t

    @hw_func
    def pdw_qualify(
        pulse_width: width_t, min_width: width_t, max_width: width_t
    ) -> verdict_t:
        is_glitch: uint1_t = pulse_width < min_width
        is_cw: uint1_t = pulse_width >= max_width
        o: verdict_t
        o.is_glitch = is_glitch
        o.is_cw = is_cw
        o.accept = (~is_glitch) & (~is_cw)
        return o

    pdw_qualify.width_t = width_t
    pdw_qualify.verdict_t = verdict_t
    return pdw_qualify, verdict_t


def make_packet_store(
    sample_t, gated_sample_t, candidate_pdw_t, width_t=uint32_t, depth=16384, n_pkts=16
):
    """Store-and-forward packet FIFO + release/flush engine (README box 3
    steps 1 and 3). Returns (packet_store, packet_store_t).

    sample_t:        the buffered payload type (the detector's complex_t).
    gated_sample_t:  make_pdw_gate's {data, valid, last} beat struct.
    candidate_pdw_t: make_pulse_detect_fsm's {toa, pulse_width, peak_power}.
    depth:           data FIFO capacity in beats. README section 3 sizes this
                     as max_width + N_pre + N_post -> 16,384. make_fifo wraps
                     a BRAM-inferable VHDL entity, so this is block RAM, not
                     flops. A `max_width` larger than this is a configuration
                     error the hardware reports (status_flags bit 2) rather
                     than detects up front.
    n_pkts:          descriptor FIFO capacity, i.e. how many completed pulses
                     may be awaiting release at once. Only exceeded if the
                     downstream consumer stalls across many short pulses; a
                     sim_assert fires if it ever is.

        packet_store(gated_in, pdw_in, pdw_in_valid, verdict, beat_status,
                     pkt_out_ready, pdw_out_ready) -> packet_store_t

    `pdw_in_valid` must coincide with `gated_in.last` -- guaranteed by the
    hysteresis SM's design (gate_last and the candidate's valid land on the
    same cycle, see make_pulse_detect_fsm), sim_asserted below because this
    engine's whole descriptor construction depends on it.

    `beat_status` is OR-ed into the packet's status_flags on every beat, for
    conditions the caller observes per sample (ADC clip, DSP overflow).
    Bit 2 (packet FIFO full) is contributed here.

    The write side is real-time and cannot stall -- that is exactly why this
    FIFO exists. The read side is a 4-state machine:

        IDLE     -- descriptor available: pop it, latch it, remaining =
                    pkt_samples. Accept -> EMIT_PDW, reject -> FLUSH.
        EMIT_PDW -- hold pdw_out.valid until pdw_out_ready. Metadata is
                    emitted BEFORE its payload, which is the order a DMA
                    consumer needs to size the transfer that follows.
        SEND_PKT -- forward `remaining` beats under real backpressure, with
                    `last` on the final one.
        FLUSH    -- pop and discard `remaining` beats at full rate.
    """

    @enum
    class store_state_t(IntEnum):
        # NB: SEND_PKT, not the more natural RELEASE -- `release` is a VHDL
        # reserved word, and an @enum member becomes a VHDL enum literal
        # verbatim, so RELEASE elaborates fine and then fails Vivado
        # synthesis with a bare "syntax error". (Native sim never sees VHDL;
        # pdw_engine_synth_top.py is what catches this class of thing.)
        # `reject` is reserved too, hence is_glitch/is_cw in verdict_t.
        IDLE = 0
        EMIT_PDW = 1
        SEND_PKT = 2
        FLUSH = 3

    @struct
    class valid_pdw_t(NamedTuple):
        # README section 4's 192-bit / 24-byte host DMA struct, field for field.
        toa: uint64_t
        pulse_width: width_t
        peak_power: uint32_t
        pkt_samples: uint32_t
        status_flags: uint16_t
        padding: uint16_t

    @struct
    class desc_t(NamedTuple):
        pdw: valid_pdw_t
        accept: uint1_t

    @struct
    class released_sample_t(NamedTuple):
        # Same shape as gated_sample_t, but this one has backpressure (the
        # store-and-forward FIFO is what makes that possible).
        data: sample_t
        valid: uint1_t
        last: uint1_t

    @struct
    class valid_pdw_stream_t(NamedTuple):
        data: valid_pdw_t
        valid: uint1_t

    @struct
    class packet_store_t(NamedTuple):
        pkt_out: released_sample_t
        pdw_out: valid_pdw_stream_t
        fifo_full: uint1_t  # sticky: some packet lost beats to a full FIFO

    data_fifo, _data_fifo_t = make_fifo(sample_t, depth)
    desc_fifo, _desc_fifo_t = make_fifo(desc_t, n_pkts)

    verdict_t = make_pdw_qualify(width_t)[1]

    @hw_func
    def packet_store(
        gated_in: gated_sample_t,
        pdw_in: candidate_pdw_t,
        pdw_in_valid: uint1_t,
        verdict: verdict_t,
        beat_status: uint16_t,
        pkt_out_ready: uint1_t,
        pdw_out_ready: uint1_t,
    ) -> packet_store_t:
        o: packet_store_t

        state: Reg[store_state_t]
        cur: Reg[valid_pdw_t]  # descriptor being released/flushed
        remaining: Reg[uint32_t]  # beats left in it
        acc_status: Reg[uint16_t]  # per-packet sticky status, write side
        acc_bad: Reg[uint1_t]  # per-packet sticky "lost a beat"
        n_pushed: Reg[uint32_t]  # beats of this packet actually in the FIFO
        fifo_full_sticky: Reg[uint1_t]

        releasing: uint1_t = state == store_state_t.SEND_PKT
        flushing: uint1_t = state == store_state_t.FLUSH

        # Data FIFO. Drain during SEND_PKT (under real backpressure) and
        # during FLUSH (at full rate, into the bit bucket).
        data_ready: uint1_t = (releasing & pkt_out_ready) | flushing
        df = data_fifo(data_ready, gated_in.data, gated_in.valid)

        # ---- write side: accumulate this packet, close it on `last` ----
        new_status: uint16_t = acc_status
        new_bad: uint1_t = acc_bad
        new_pushed: uint32_t = n_pushed
        if gated_in.valid:
            new_status = acc_status | beat_status
            if df.data_in_ready:
                new_pushed = n_pushed + 1
            else:
                # Beat lost. Record it, and force-reject the packet: its
                # contents are no longer what the detector saw.
                new_status = new_status | STATUS_PKT_FIFO_FULL
                new_bad = 1
                fifo_full_sticky = 1

        desc_push: uint1_t = gated_in.valid & gated_in.last
        sim_assert(
            (~desc_push) | pdw_in_valid,
            "packet_store: gate_last without a coincident candidate -- the "
            "hysteresis SM's gate_last/candidate pairing invariant is broken",
        )

        desc_in: desc_t
        desc_in.accept = verdict.accept & (~new_bad)
        desc_in.pdw.toa = pdw_in.toa
        desc_in.pdw.pulse_width = pdw_in.pulse_width
        desc_in.pdw.peak_power = pdw_in.peak_power.val[PEAK_POWER_BITS - 1 : 0]
        desc_in.pdw.pkt_samples = new_pushed
        desc_in.pdw.status_flags = new_status
        desc_in.pdw.padding = 0

        if desc_push:
            acc_status = 0  # re-arm for the next packet
            acc_bad = 0
            n_pushed = 0
        else:
            acc_status = new_status
            acc_bad = new_bad
            n_pushed = new_pushed

        # ---- descriptor FIFO ----
        desc_pop: uint1_t = state == store_state_t.IDLE
        sf = desc_fifo(desc_pop, desc_in, desc_push)
        sim_assert(
            (~desc_push) | sf.data_in_ready,
            f"packet_store: descriptor FIFO full (n_pkts={n_pkts}) -- more "
            "completed pulses are awaiting release than it can hold; increase "
            "n_pkts or unblock the downstream consumer",
        )

        # ---- read side ----
        o.pkt_out.data = df.data_out
        o.pkt_out.valid = releasing & df.data_out_valid
        o.pkt_out.last = releasing & df.data_out_valid & (remaining == 1)
        o.pdw_out.data = cur
        o.pdw_out.valid = state == store_state_t.EMIT_PDW
        o.fifo_full = fifo_full_sticky

        if state == store_state_t.IDLE:
            if sf.data_out_valid:
                cur = sf.data_out.pdw
                remaining = sf.data_out.pdw.pkt_samples
                if sf.data_out.pdw.pkt_samples == 0:
                    # Only reachable when a full FIFO ate every beat of the
                    # packet, which also forces accept=0 -- nothing buffered
                    # to flush, so skip straight back to IDLE rather than
                    # waiting forever for beats that were never stored.
                    state = store_state_t.IDLE
                elif sf.data_out.accept:
                    state = store_state_t.EMIT_PDW
                else:
                    state = store_state_t.FLUSH
        elif state == store_state_t.EMIT_PDW:
            if pdw_out_ready:
                state = store_state_t.SEND_PKT
        elif state == store_state_t.SEND_PKT:
            if df.data_out_valid & pkt_out_ready:
                if remaining == 1:
                    state = store_state_t.IDLE
                else:
                    remaining = remaining - 1
        else:  # FLUSH
            if df.data_out_valid:
                if remaining == 1:
                    state = store_state_t.IDLE
                else:
                    remaining = remaining - 1

        return o

    packet_store.sample_t = sample_t
    packet_store.width_t = width_t
    packet_store.valid_pdw_t = valid_pdw_t
    packet_store.desc_t = desc_t
    packet_store.released_sample_t = released_sample_t
    packet_store.valid_pdw_stream_t = valid_pdw_stream_t
    packet_store.store_state_t = store_state_t
    packet_store.depth = depth
    packet_store.n_pkts = n_pkts
    return packet_store, packet_store_t


def make_pdw_engine(detect_pulses, depth=16384, n_pkts=16):
    """The whole README box 3, wired to a `detect_pulses` instance. Returns
    (pdw_engine, pdw_engine_t).

        pdw_engine(gated_in, pdw_in_if, dsp_overflow, min_width, max_width,
                   pkt_out_ready, pdw_out_ready) -> pdw_engine_t

        pdw_engine_t fields:
          .pdw_in_if (detect_pulses.out_fb_t) -- the candidate stream's ready,
            paired with the pdw_in_if arg. Always 1: the engine latches the
            candidate into the descriptor FIFO on the cycle it arrives, so it
            can never stall Path A (which cannot be stalled anyway -- see
            make_pulse_detect_fsm's notes on `overflow`).
          .pkt_out (released_sample_t) -- the qualified AXIS packet.
          .pdw_out (valid_pdw_stream_t) -- the host-DMA metadata.
          .verdict (verdict_t) -- this cycle's qualification of the candidate
            on pdw_in_if, exposed for observability/testbenches.
          .fifo_full (uint1_t) -- sticky packet-FIFO-full.

    `peak_power` is truncated from the detector's full-precision `power_t`
    (46 bits with the default dc_k/ma_n) to README section 4's uint32_t. Keep
    a pulse's peak under 2**32 in power_t's scaled units or this field wraps
    silently -- the same caveat top.py's candidate_pdw_peak_power port already
    carries, documented in README section 4.

    ADC clip (status_flags bit 0) is detected on the STORED sample -- the
    time-aligned raw I/Q that actually goes into the packet -- rather than on
    the live ADC input, so the flag describes the packet the host receives.
    """
    rail_t = detect_pulses.rail_t
    rail_lo, rail_hi = data_range(rail_t)
    rail_val_t = rail_t.typeof("val")

    packet_store, _packet_store_t = make_packet_store(
        detect_pulses.complex_t,
        detect_pulses.gated_sample_t,
        detect_pulses.candidate_pdw_t,
        width_t=detect_pulses.width_t,
        depth=depth,
        n_pkts=n_pkts,
    )
    pdw_qualify, verdict_t = make_pdw_qualify(detect_pulses.width_t)

    @struct
    class pdw_engine_t(NamedTuple):
        pdw_in_if: detect_pulses.out_fb_t
        pkt_out: packet_store.released_sample_t
        pdw_out: packet_store.valid_pdw_stream_t
        verdict: verdict_t
        fifo_full: uint1_t

    @hw_func
    def pdw_engine(
        gated_in: detect_pulses.gated_sample_t,
        pdw_in_if: detect_pulses.out_fwd_t,
        dsp_overflow: uint1_t,
        min_width: detect_pulses.width_t,
        max_width: detect_pulses.width_t,
        pkt_out_ready: uint1_t,
        pdw_out_ready: uint1_t,
    ) -> pdw_engine_t:
        candidate = pdw_in_if.stream.data
        v = pdw_qualify(candidate.pulse_width, min_width, max_width)

        # Per-beat status contributions (see this factory's docstring on why
        # clip is measured on the stored sample).
        i_val: rail_val_t = gated_in.data.i.val
        q_val: rail_val_t = gated_in.data.q.val
        clipped: uint1_t = (
            (i_val == rail_hi) | (i_val == rail_lo) | (q_val == rail_hi) | (q_val == rail_lo)
        )
        # Both ternary branches must be the SAME type, so the set-bit
        # constants need widening to uint16_t explicitly -- a bare
        # `STATUS_ADC_CLIP` literal infers as uint1_t and the elaborator
        # rejects the mix (native sim does not, which is what
        # pdw_engine_synth_top.py is for).
        zero16: uint16_t = 0
        clip_set: uint16_t = STATUS_ADC_CLIP
        dsp_set: uint16_t = STATUS_DSP_OVERFLOW
        clip_bit: uint16_t = clip_set if clipped else zero16
        dsp_bit: uint16_t = dsp_set if dsp_overflow else zero16
        beat_status: uint16_t = clip_bit | dsp_bit

        ps = packet_store(
            gated_in,
            candidate,
            pdw_in_if.stream.valid,
            v,
            beat_status,
            pkt_out_ready,
            pdw_out_ready,
        )

        o: pdw_engine_t
        o.pdw_in_if.ready = 1  # never stalls Path A -- see the docstring
        o.pkt_out = ps.pkt_out
        o.pdw_out = ps.pdw_out
        o.verdict = v
        o.fifo_full = ps.fifo_full
        return o

    pdw_engine.detect_pulses = detect_pulses
    pdw_engine.packet_store = packet_store
    pdw_engine.pdw_qualify = pdw_qualify
    pdw_engine.verdict_t = verdict_t
    pdw_engine.valid_pdw_t = packet_store.valid_pdw_t
    pdw_engine.released_sample_t = packet_store.released_sample_t
    pdw_engine.valid_pdw_stream_t = packet_store.valid_pdw_stream_t
    pdw_engine.width_t = detect_pulses.width_t
    pdw_engine.depth = depth
    pdw_engine.n_pkts = n_pkts
    return pdw_engine, pdw_engine_t
