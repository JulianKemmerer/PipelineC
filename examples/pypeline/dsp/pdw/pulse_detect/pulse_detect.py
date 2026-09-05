# pyright: reportInvalidTypeForm=none
"""Hysteresis SM + Extract Candidate PDW -- steps 3-4 of Path A ("Detect &
Measure") in the AIR7310 PDW pipeline (see ../README.md). Consumes the
conditioned power stream out of dsp/dc_block.py + dsp/moving_avg.py and
produces:

  1. A valid/ready `candidate_pdw_t{toa, pulse_width, peak_power}` per
     detected pulse (a raw, unvalidated guess -- glitch/CW rejection against
     min_width/max_width happens downstream in the storage engine, per the
     README's architecture split, EXCEPT max_width also force-terminates a
     pulse here -- see below).
  2. A real-time AXIS-style gate stream (`gate_valid`/`gate_last`), the
     control half of what becomes the outbound packet once combined with
     Path B's delay-line FIFO supplying the time-aligned raw I/Q `tdata`.

Both outputs are one block (not two) because the hysteresis state machine
already holds everything the candidate needs (running width, running peak) --
"extract" is just the emit action on the SM's PULSE-exit edge.

Why max_width force-terminates here, not only downstream: a CW/jamming input
never drops below threshold_low, so without a cap the SM would wedge in PULSE
forever and the downstream engine would never receive a candidate to apply its
"CW Rejection" to. A RECOVER state makes one CW event emit exactly ONE
candidate (of width == max_width) rather than one every max_width cycles, and
the downstream engine rejects it by seeing pulse_width >= max_width.

The force-close candidate is held one accepted sample before being presented,
unlike a normal close. A normal close is triggered BY the first
below-threshold sample -- the same sample that drives gate_last -- so it
already coincides. A force-close is triggered by an IN-pulse sample, one
earlier than the RECOVER transition that makes gate_last fire, so without the
hold a CW candidate would arrive one cycle ahead of its own packet's end
marker. See the force-close branch's comment.

Why the gate stream is delayed one accepted sample: AXIS requires `last` to be
asserted ON the final valid beat, but a sample is only known to be the pulse's
last one once the NEXT sample falls below threshold_low (a one-sample
lookahead). So gate_valid/gate_last are registered one accepted sample behind
the power stream -- gate_last coincides with the final gate_valid beat instead
of trailing it by a cycle (which would be illegal AXIS: last-without-valid).
Convenient consequence: gate_last and the candidate stream's valid land on the
SAME cycle, so a consumer sees the packet's end marker and its metadata
together. This makes the gate path's latency 2 relative to the input sample
(vs. 1 for the candidate) -- `pulse_detect_fsm.gate_latency`/`.pdw_latency`,
the single source of truth for both numbers (the README's L_sm placeholder of
1 is a sizing estimate, not this). Path B does not need to know either number:
`gate_advance` realises the gate path's own delay in hardware, and the delay
line drains off it (see make_delay_line).

This is a genuine recurrence (state/width/peak each depend on their own
previous value), so it is NOT run through AUTOPIPELINE/make_stream_pipeline
like the pure feedforward dsp/ blocks -- the same inherent limit dc_block.py
documents for its IIR loop. The critical path is one compare feeding a mux, so
this isn't expected to need it; if it ever misses timing, above_high/below_low
are pure feedforward and can be moved into an autopipelined comparator stage
ahead of the FSM.

`toa` is implemented: a free-running counter of this block's own accepted
input samples, latched on the IDLE->PULSE edge. It counts CONDITIONED-power
samples, so it trails the raw ADC sample index by the DSP chain's latency --
a constant bias this block cannot see and therefore does not correct.

Remaining TODOs, owned by the storage engine, not this block:
  - gate_ready / backpressure on the gate stream: the SM is real-time and
    cannot stall, so a not-ready storage FIFO means dropped samples. The
    storage engine absorbs this with a store-and-forward FIFO and reports it
    via the README's status_flags "Packet FIFO Full" bit rather than pushing
    back here.
  - N_pre/N_post margins: the real packet is WIDER than this block's gate
    window (README: pkt_samples = N_pre + width + N_post). Pre-margin comes
    from reading the delay FIFO early; post-margin extends gate_valid past
    the pulse. Both belong to the storage engine.
  - overflow is sticky until reset; a clear input is a TODO for when the
    status_flags register exists.
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
    uint32_t,
    uint64_t,
)

from fixed_point import make_fixed_t
from stream.stream import make_stream_interface, make_stream_t
from fifo import make_fifo
from dsp.magnitude import make_magnitude
from dsp.dc_block import make_dc_block
from dsp.moving_avg import make_moving_avg


def make_pulse_detect_fsm(data_t, width_t=uint32_t, handshake="elastic"):
    """Build the hysteresis SM / candidate-PDW extractor. Returns
    (pulse_detect_fsm, pulse_detect_fsm_t).

    data_t:    fixed_t conditioned-power sample format (the README's power
               format is make_fixed_t(32, 0, signed=False) == uint32_t).
    width_t:   integer type for pulse_width / max_width (default uint32_t,
               matching the README's Configuration Parameters table).
    handshake: "elastic"    -> pulse_detect_fsm(stream_in_if: in_intrf.fwd_t,
                                             pdw_out_if: out_intrf.fb_t,
                                             threshold_high, threshold_low,
                                             max_width) -> pulse_detect_fsm_t
                               (candidate stream is always valid/ready;
                               only the INPUT power stream's handshake mode
                               varies)
               "valid_only" -> pulse_detect_fsm(stream_in_if: make_stream_t(data_t),
                                             pdw_out_if: out_intrf.fb_t,
                                             threshold_high, threshold_low,
                                             max_width) -> pulse_detect_fsm_t

    Besides gate_valid/gate_last, the returned struct carries `gate_advance`:
    1 on exactly those cycles where the gate output registers are presenting a
    real per-sample decision (i.e. where gate_valid COULD be 1), 0 while the
    gate register chain is still filling after reset and on any cycle with no
    accepted input. It is built as the structural twin of the gate_valid_r
    chain -- the same two `if accepted:`-gated registers, with in_pulse
    replaced by a constant 1 -- which is what makes it exactly co-timed with
    gate_valid by construction rather than by a matching hand-counted delay.
    Path B's delay line uses it as its drain enable (see make_delay_line and
    make_detect_pulses), so raw I/Q advances in lockstep with the gate stream
    and no latency constant appears anywhere; extend the gate chain and Path
    B's alignment follows for free.

    The returned `pulse_detect_fsm` carries metadata attributes:
    .data_t .width_t .candidate_pdw_t .state_t .handshake .gate_latency
    .in_fwd_t/.out_fwd_t (elastic) .in_stream_t/.out_stream_t (valid_only)
    .in_fb_t/.out_fb_t .in_intrf/.out_intrf
    """
    data_val_t = data_t.typeof("val")

    @enum
    class state_t(IntEnum):
        IDLE = 0
        PULSE = 1
        RECOVER = 2  # CW: pulse already emitted at max_width, waiting to re-arm

    @struct
    class candidate_pdw_t(NamedTuple):
        # toa: sampled off a free-running counter on the IDLE->PULSE edge (see
        # toa_counter/toa_latch below). It counts THIS block's own accepted
        # input samples, i.e. the conditioned power stream -- which trails the
        # raw ADC sample index by the DSP chain's latency. That bias is a
        # constant, so it is documented rather than corrected for here (this
        # block cannot see its own upstream latency).
        toa: uint64_t
        pulse_width: width_t
        peak_power: data_t

    out_intrf = make_stream_interface(candidate_pdw_t)

    if handshake == "elastic":
        in_intrf = make_stream_interface(data_t)

        @struct
        class pulse_detect_fsm_t(NamedTuple):
            stream_in_if: in_intrf.fb_t  # input port's reverse half travels out
            pdw_out_if: out_intrf.fwd_t  # output port's feedforward half travels out
            gate_valid: uint1_t
            gate_last: uint1_t
            gate_advance: uint1_t
            overflow: uint1_t

        @hw_func
        def pulse_detect_fsm(
            stream_in_if: in_intrf.fwd_t,
            pdw_out_if: out_intrf.fb_t,
            threshold_high: data_t,
            threshold_low: data_t,
            max_width: width_t,
        ) -> pulse_detect_fsm_t:
            o: pulse_detect_fsm_t
            state: Reg[state_t]
            width: Reg[width_t]
            peak: Reg[data_val_t]
            pdw_reg: Reg[out_intrf.stream_t]  # 1-deep output slot (never .fwd_t)
            overflow: Reg[uint1_t]
            held_in_pulse: Reg[uint1_t]  # previous accepted sample's gate status
            gate_valid_r: Reg[uint1_t]
            gate_last_r: Reg[uint1_t]
            gate_armed: Reg[uint1_t]  # sticky: >=1 accepted sample seen
            gate_advance_r: Reg[uint1_t]
            toa_counter: Reg[uint64_t]  # free-running, counts accepted samples
            toa_latch: Reg[uint64_t]  # sampled on the IDLE->PULSE edge
            pdw_pending: Reg[uint1_t]  # CW force-close, held one sample
            pdw_pending_data: Reg[candidate_pdw_t]

            # Present the slot, THEN drain it -- blocking assignment makes the
            # same-cycle consume/refill handoff work with no extra logic (the
            # axi/axis.py make_dwidth_widen ordering).
            o.pdw_out_if.stream = pdw_reg
            if pdw_reg.valid & pdw_out_if.ready:
                pdw_reg.valid = 0

            o.stream_in_if.ready = ~pdw_reg.valid  # post-drain
            accepted: uint1_t = stream_in_if.stream.valid & o.stream_in_if.ready

            p: data_val_t = stream_in_if.stream.data.val
            above_high: uint1_t = p > threshold_high.val
            below_low: uint1_t = p < threshold_low.val

            # Is the sample presented THIS cycle inside the pulse?
            in_pulse: uint1_t = 0
            if state == state_t.IDLE:
                in_pulse = above_high
            elif state == state_t.PULSE:
                in_pulse = ~below_low
            # RECOVER -> 0: the CW pulse was already closed at max_width.

            # Gate stream out: the PREVIOUS accepted sample, so `last` is known.
            o.gate_valid = gate_valid_r
            o.gate_last = gate_last_r
            o.gate_advance = gate_advance_r

            if accepted:
                gate_valid_r = held_in_pulse
                gate_last_r = held_in_pulse & ~in_pulse  # prev sample was final
                held_in_pulse = in_pulse
                # Structural twin of the gate_valid_r chain above, with
                # in_pulse replaced by a constant 1 -- see gate_advance's
                # note in this factory's docstring.
                gate_advance_r = gate_armed
                gate_armed = 1

                # Release a held CW candidate (see the force-close branch
                # below). Reads the PRE-update register, so the sample that
                # set pdw_pending does not also release it -- the release
                # happens exactly one accepted sample later, which is what
                # lands it on the same cycle as its own gate_last.
                if pdw_pending:
                    if pdw_reg.valid:
                        overflow = 1  # unreachable in elastic mode
                    pdw_reg.data = pdw_pending_data
                    pdw_reg.valid = 1
                    pdw_pending = 0

                if state == state_t.IDLE:
                    if above_high:
                        state = state_t.PULSE
                        width = 1  # this sample counts
                        peak = p
                        toa_latch = toa_counter  # pre-increment: THIS sample
                elif state == state_t.PULSE:
                    if below_low:
                        # Terminating sample NOT counted in pulse_width.
                        if pdw_reg.valid:
                            overflow = 1  # unreachable in elastic mode
                        pdw_reg.data = candidate_pdw_t(
                            toa=toa_latch,
                            pulse_width=width,
                            peak_power=data_t(val=peak),
                        )
                        pdw_reg.valid = 1
                        state = state_t.IDLE
                    else:
                        new_width: width_t = width + 1
                        new_peak: data_val_t = p if p > peak else peak
                        if new_width >= max_width:
                            # HELD one accepted sample, unlike the normal
                            # close above. A normal close is triggered BY the
                            # first below-threshold sample -- the same sample
                            # that drives gate_last -- so emitting immediately
                            # already coincides with gate_last. A force-close
                            # is triggered by an IN-pulse sample, one earlier
                            # than the RECOVER transition that makes
                            # gate_last fire, so emitting immediately would
                            # put the candidate one cycle AHEAD of its own
                            # packet's end marker. Holding it restores the
                            # invariant this module's docstring promises, and
                            # which the storage engine's descriptor
                            # construction depends on.
                            pdw_pending_data = candidate_pdw_t(
                                toa=toa_latch,
                                pulse_width=new_width,
                                peak_power=data_t(val=new_peak),
                            )
                            pdw_pending = 1
                            state = state_t.RECOVER
                        else:
                            width = new_width
                            peak = new_peak
                else:  # RECOVER
                    if below_low:
                        state = state_t.IDLE  # re-arm; one CW -> one candidate

                toa_counter = toa_counter + 1  # last: every read above is pre-increment
            else:
                gate_valid_r = 0  # no gate beat this cycle
                gate_last_r = 0
                gate_advance_r = 0

            o.overflow = overflow  # last, so it reads post-update
            return o

    elif handshake == "valid_only":
        in_stream_t = make_stream_t(data_t)

        @struct
        class pulse_detect_fsm_t(NamedTuple):
            pdw_out_if: out_intrf.fwd_t  # output port's feedforward half travels out
            gate_valid: uint1_t
            gate_last: uint1_t
            gate_advance: uint1_t
            overflow: uint1_t

        @hw_func
        def pulse_detect_fsm(
            stream_in_if: in_stream_t,
            pdw_out_if: out_intrf.fb_t,
            threshold_high: data_t,
            threshold_low: data_t,
            max_width: width_t,
        ) -> pulse_detect_fsm_t:
            o: pulse_detect_fsm_t
            state: Reg[state_t]
            width: Reg[width_t]
            peak: Reg[data_val_t]
            pdw_reg: Reg[out_intrf.stream_t]  # 1-deep output slot (never .fwd_t)
            overflow: Reg[uint1_t]
            held_in_pulse: Reg[uint1_t]
            gate_valid_r: Reg[uint1_t]
            gate_last_r: Reg[uint1_t]
            gate_armed: Reg[uint1_t]  # sticky: >=1 accepted sample seen
            gate_advance_r: Reg[uint1_t]
            toa_counter: Reg[uint64_t]  # free-running, counts accepted samples
            toa_latch: Reg[uint64_t]  # sampled on the IDLE->PULSE edge
            pdw_pending: Reg[uint1_t]  # CW force-close, held one sample
            pdw_pending_data: Reg[candidate_pdw_t]

            o.pdw_out_if.stream = pdw_reg
            if pdw_reg.valid & pdw_out_if.ready:
                pdw_reg.valid = 0

            accepted: uint1_t = stream_in_if.valid  # always-consuming input

            p: data_val_t = stream_in_if.data.val
            above_high: uint1_t = p > threshold_high.val
            below_low: uint1_t = p < threshold_low.val

            in_pulse: uint1_t = 0
            if state == state_t.IDLE:
                in_pulse = above_high
            elif state == state_t.PULSE:
                in_pulse = ~below_low

            o.gate_valid = gate_valid_r
            o.gate_last = gate_last_r
            o.gate_advance = gate_advance_r

            if accepted:
                gate_valid_r = held_in_pulse
                gate_last_r = held_in_pulse & ~in_pulse
                held_in_pulse = in_pulse
                # Structural twin of the gate_valid_r chain above, with
                # in_pulse replaced by a constant 1 -- see gate_advance's
                # note in this factory's docstring.
                gate_advance_r = gate_armed
                gate_armed = 1

                # Release a held CW candidate -- see the elastic branch's
                # comment on the force-close below for why it is held.
                if pdw_pending:
                    if pdw_reg.valid:
                        overflow = 1
                    pdw_reg.data = pdw_pending_data
                    pdw_reg.valid = 1
                    pdw_pending = 0

                if state == state_t.IDLE:
                    if above_high:
                        state = state_t.PULSE
                        width = 1
                        peak = p
                        toa_latch = toa_counter  # pre-increment: THIS sample
                elif state == state_t.PULSE:
                    if below_low:
                        if pdw_reg.valid:
                            overflow = 1  # reachable: input can't be stalled
                        pdw_reg.data = candidate_pdw_t(
                            toa=toa_latch,
                            pulse_width=width,
                            peak_power=data_t(val=peak),
                        )
                        pdw_reg.valid = 1
                        state = state_t.IDLE
                    else:
                        new_width: width_t = width + 1
                        new_peak: data_val_t = p if p > peak else peak
                        if new_width >= max_width:
                            # Held one accepted sample so it coincides with
                            # its own gate_last -- see the elastic branch.
                            pdw_pending_data = candidate_pdw_t(
                                toa=toa_latch,
                                pulse_width=new_width,
                                peak_power=data_t(val=new_peak),
                            )
                            pdw_pending = 1
                            state = state_t.RECOVER
                        else:
                            width = new_width
                            peak = new_peak
                else:  # RECOVER
                    if below_low:
                        state = state_t.IDLE

                toa_counter = toa_counter + 1  # last: every read above is pre-increment
            else:
                gate_valid_r = 0
                gate_last_r = 0
                gate_advance_r = 0

            o.overflow = overflow
            return o

    else:
        raise ValueError(
            f"make_pulse_detect_fsm: unsupported handshake {handshake!r}, "
            "expected 'elastic' or 'valid_only'"
        )

    pulse_detect_fsm.data_t = data_t
    pulse_detect_fsm.width_t = width_t
    pulse_detect_fsm.candidate_pdw_t = candidate_pdw_t
    pulse_detect_fsm.state_t = state_t
    pulse_detect_fsm.handshake = handshake
    # Accepted-sample stages between an input sample and the gate output beat
    # it produces (held_in_pulse -> gate_valid_r -> presented pre-update).
    # The single source of truth for this number: make_detect_pulses' own
    # .gate_latency derives from it, and gate_advance realises it in hardware.
    pulse_detect_fsm.gate_latency = 2
    # Accepted-sample stages between the pulse-terminating sample and the
    # candidate appearing on pdw_out_if (pdw_reg, presented pre-update).
    pulse_detect_fsm.pdw_latency = 1
    pulse_detect_fsm.in_fwd_t = in_intrf.fwd_t if handshake == "elastic" else None
    pulse_detect_fsm.in_stream_t = in_stream_t if handshake == "valid_only" else None
    pulse_detect_fsm.out_fwd_t = out_intrf.fwd_t
    pulse_detect_fsm.out_stream_t = None
    pulse_detect_fsm.in_fb_t = in_intrf.fb_t if handshake == "elastic" else None
    pulse_detect_fsm.out_fb_t = out_intrf.fb_t
    pulse_detect_fsm.in_intrf = in_intrf if handshake == "elastic" else None
    pulse_detect_fsm.out_intrf = out_intrf
    return pulse_detect_fsm, pulse_detect_fsm_t


def make_delay_line(data_t, depth=64):
    """Path B: DELAY LINE FIFO. Returns (delay_line, data_t) (output type same
    as input -- this only delays, it doesn't transform).

    SELF-TIMED, not fixed-depth. The delay is set by *when draining starts*,
    not by `depth`:

        delay_line(sample_in, push_en, drain_en) -> data_t

    Push on every valid input sample; hold `drain_en` low while Path A's
    pipeline is still filling, then raise it once Path A starts producing gate
    beats. A FWFT FIFO held un-drained loads its output register once (on the
    second push) and then freezes, so the queue behind it grows by one entry
    per push; the moment `drain_en` goes high the frozen word comes out and
    every subsequent drain advances by one. The achieved delay is therefore
    exactly the number of pushes that happened before the first drain -- the
    FIFO's own 2-cycle push-to-valid latency is absorbed into the hold window
    rather than added to it.

    Callers must drive `drain_en` from a signal that is co-timed with the
    consumer of this output. make_detect_pulses uses pulse_detect_fsm's
    `gate_advance` (see there), which makes Path A's latency cancel exactly,
    with no cycle count written down anywhere.

    Counting *pushes and drains* rather than cycles is also what keeps a
    gapped input correct: Path A's DSP chain advances its own state only on
    valid samples, so Path B has to as well.

    depth: capacity only -- it does NOT set the delay. It must merely be large
    enough to hold the samples that accumulate during the hold window, i.e.
    2**ceil(log2(depth)) >= (pushes before the first drain). Over-sizing is
    free for correctness under this scheme, and the FIFO is a BRAM-inferable
    VHDL entity, so round up generously rather than sizing it precisely. A
    sim_assert below fails loudly if it is ever too small (silently dropping a
    push would corrupt the alignment with no other symptom).
    """
    fifo_func, _fifo_t = make_fifo(data_t, depth)

    @hw_func
    def delay_line(
        sample_in: data_t, push_en: uint1_t, drain_en: uint1_t
    ) -> data_t:
        f = fifo_func(drain_en, sample_in, push_en)
        sim_assert(
            (~push_en) | f.data_in_ready,
            f"pulse_detect delay_line: FIFO full (depth={depth}) -- the hold "
            "window before draining starts is longer than the delay line can "
            "buffer; increase make_detect_pulses' delay_depth",
        )
        return f.data_out

    delay_line.data_t = data_t
    delay_line.depth = depth
    return delay_line, data_t


def make_pdw_gate(data_t):
    """Path A/B combinator: gates an (already delay_line-delayed) raw sample
    with the Hysteresis SM's real-time gate_valid/gate_last, producing the
    bounded pulse sample stream. Returns (pdw_gate, gated_sample_t).

    Not an AXI-Stream struct -- data/valid/last with no ready, a real-time,
    can't-stall forwarding path (same as the gate signals it wraps); AXIS
    framing only happens at the real top-level port, per this project's
    existing convention.
    """

    @struct
    class gated_sample_t(NamedTuple):
        data: data_t
        valid: uint1_t
        last: uint1_t

    @hw_func
    def pdw_gate(
        delayed_sample: data_t, gate_valid: uint1_t, gate_last: uint1_t
    ) -> gated_sample_t:
        o: gated_sample_t
        o.data = delayed_sample
        o.valid = gate_valid
        o.last = gate_last
        return o

    pdw_gate.data_t = data_t
    pdw_gate.gated_sample_t = gated_sample_t
    return pdw_gate, gated_sample_t


def make_detect_pulses(rail_t=None, dc_k=10, ma_n=4, width_t=uint32_t, delay_depth=64):
    """Path A: DETECT & MEASURE -- the README's whole "TIME-ALIGNED DETECT &
    DELAY MODULE" Path A box, magnitude -> dc_block -> moving_avg ->
    pulse_detect_fsm, composed into one hw_func. Returns
    (detect_pulses, detect_pulses_t).

    rail_t:  fixed_t I/Q rail format; default make_fixed_t(16, 0, signed=True)
             (a raw int16 rail, matching pulse_gen.py's iq_t fields).
    dc_k:    dc_block leaky-integrator shift (see dc_block.py; default matches
             dc_block.py's own default).
    ma_n:    moving_avg window, must be a power of two (see moving_avg.py).
             Neither dc_k nor ma_n is specified by the README (which only
             gives latency estimates for FIFO sizing, not real filter
             parameters) -- both are placeholder defaults, tunable here.
    width_t: integer type for pulse_width/max_width (see make_pulse_detect_fsm).

    Input: a raw I/Q stream, `handshake="valid_only"` (a fixed-rate ADC feed
    that is never stalled -- see this module's own docstring above for why the
    WHOLE internal DSP chain (magnitude/dc_block/moving_avg) is valid_only:
    chaining two elastic (valid/ready) stages back to back by nested calls
    doesn't work here, since each stage's ready-out is a registered value that
    can only be obtained by calling that stage, which itself needs the
    upstream stage's data -- a genuine circular call-order dependency in this
    call-graph composition model. valid_only sidesteps it entirely (pure
    feedforward, no readiness anywhere upstream of pulse_detect_fsm), which is
    also the physically correct model: nothing upstream of this module can
    ever be back-pressured.

    Output: pulse_detect_fsm's normal candidate_pdw_t elastic valid/ready stream
    (the one real backpressure boundary here -- see make_pulse_detect_fsm's
    valid_only-mode notes on `overflow`), plus `gated_out`: the bounded pulse
    sample stream (see make_pdw_gate) formed by gating the raw input sample --
    delayed by the Path B delay line (see make_delay_line) -- with the FSM's
    real-time gate_valid/gate_last.

    Path B alignment is SELF-TIMED and exact: the delay line pushes on every
    valid input sample and drains on the FSM's `gate_advance`, so it advances
    one raw sample per gate beat slot and holds off exactly as long as Path A
    takes to fill. Each gate beat therefore carries precisely the raw sample
    whose power produced it, for any DSP latency, with no cycle count written
    down anywhere. The realised delay -- get_dsp_latency() + gate_latency
    input samples -- is exposed as `get_path_b_delay()` for golden models;
    hardware never reads it.

    `delay_depth` is capacity only, NOT the delay (that was the pre-fix
    behaviour, where the FIFO was pushed and drained every cycle and so only
    ever showed its own incidental 2-cycle latency regardless of depth). It
    must exceed get_path_b_delay(); the default 64 leaves ample room for a
    real build's AUTOPIPELINE latencies, and make_delay_line sim_asserts if it
    is ever too small. N_pre/N_post margins are still unbuilt and belong to
    the storage engine -- N_pre will deepen this hold window further.

    `dc_block.out_t`/`moving_avg.out_t` are full precision (no out_t= passed
    anywhere in the chain), so threshold_high/threshold_low/peak_power are
    typed as `detect_pulses.power_t` (== moving_avg.out_t), NOT a fixed
    README-shaped uint32_t/make_fixed_t(32, 0) -- unlike
    pulse_detect_synth_top.py, which hardcodes that type for the bare
    hysteresis-SM-only block.

    The returned `detect_pulses` carries metadata attributes:
    .rail_t .complex_t .power_t .width_t .candidate_pdw_t .gated_sample_t
    .delay_depth .in_stream_t .out_fb_t .out_fwd_t .magnitude .dc_block
    .moving_avg .pdw_latency .gate_latency .get_dsp_latency()
    .get_path_b_delay()
    """
    rail_t_actual = rail_t or make_fixed_t(16, 0, signed=True)

    magnitude, _magnitude_t = make_magnitude(rail_t_actual, handshake="valid_only")
    dc_block, _dc_block_t = make_dc_block(magnitude.out_t, k=dc_k, handshake="valid_only")
    moving_avg, _moving_avg_t = make_moving_avg(dc_block.out_t, ma_n, handshake="valid_only")
    detect_fsm, detect_fsm_t = make_pulse_detect_fsm(
        moving_avg.out_t, width_t=width_t, handshake="valid_only"
    )
    delay_line, _delay_data_t = make_delay_line(magnitude.complex_t, depth=delay_depth)
    pdw_gate, gated_sample_t = make_pdw_gate(magnitude.complex_t)

    in_stream_t = make_stream_t(magnitude.complex_t)

    @struct
    class detect_pulses_t(NamedTuple):
        pdw_out_if: detect_fsm.out_fwd_t
        gated_out: gated_sample_t
        overflow: uint1_t

    @hw_func
    def detect_pulses(
        stream_in_if: in_stream_t,
        pdw_out_if: detect_fsm.out_fb_t,
        threshold_high: moving_avg.out_t,
        threshold_low: moving_avg.out_t,
        max_width: width_t,
    ) -> detect_pulses_t:
        mag_o = magnitude(stream_in_if)
        dc_o = dc_block(mag_o)
        avg_o = moving_avg(dc_o)
        pd_o = detect_fsm(
            avg_o, pdw_out_if, threshold_high, threshold_low, max_width
        )
        # Path B advances one raw sample per gate-stream beat slot, so the two
        # paths stay locked together with no latency constant anywhere -- see
        # make_delay_line and pulse_detect_fsm's gate_advance.
        delayed_sample = delay_line(
            stream_in_if.data, stream_in_if.valid, pd_o.gate_advance
        )
        gate_o = pdw_gate(delayed_sample, pd_o.gate_valid, pd_o.gate_last)
        # gate_valid without gate_advance would mean Path B never popped the
        # sample that beat is carrying -- impossible by construction (they are
        # the same register chain), so this catches a future edit that
        # desynchronizes them, rather than letting it surface as opaque
        # packet-content garbage.
        sim_assert(
            (~pd_o.gate_valid) | pd_o.gate_advance,
            "detect_pulses: gate_valid asserted without gate_advance -- Path A "
            "and Path B have desynchronized",
        )

        o: detect_pulses_t
        o.pdw_out_if = pd_o.pdw_out_if
        o.gated_out = gate_o
        o.overflow = pd_o.overflow
        return o

    detect_pulses.rail_t = rail_t_actual
    detect_pulses.complex_t = magnitude.complex_t
    detect_pulses.power_t = moving_avg.out_t
    detect_pulses.width_t = width_t
    detect_pulses.candidate_pdw_t = detect_fsm.candidate_pdw_t
    detect_pulses.gated_sample_t = gated_sample_t
    detect_pulses.delay_depth = delay_depth
    detect_pulses.in_stream_t = in_stream_t
    detect_pulses.out_fb_t = detect_fsm.out_fb_t
    detect_pulses.out_fwd_t = detect_fsm.out_fwd_t

    # The three DSP sub-instances, exposed so a caller (a golden-model
    # testbench) can drive dsp_tb.golden_magnitude/golden_dc_block/
    # golden_moving_avg directly off the SAME instances this factory built,
    # rather than reconstructing a second, potentially-diverging set.
    detect_pulses.magnitude = magnitude
    detect_pulses.dc_block = dc_block
    detect_pulses.moving_avg = moving_avg

    # Latency metadata -- lazy accessors (see magnitude.py's identical
    # comment for why): reading .latency triggers pipelinec's pin-and-confirm
    # loop, so a caller that merely CONSTRUCTS this block must not pay for it.
    # pdw_latency/gate_latency are fixed Reg stages inside the FSM (not
    # affected by autopipelining, since the FSM itself is never autopipelined
    # -- see make_pulse_detect_fsm's docstring on why it's a genuine
    # recurrence), and are re-exported from there rather than restated.
    detect_pulses.pdw_latency = detect_fsm.pdw_latency
    detect_pulses.gate_latency = detect_fsm.gate_latency
    detect_pulses.get_dsp_latency = lambda: (
        magnitude.get_latency() + dc_block.get_latency() + moving_avg.get_latency()
    )
    # Path B's realised delay, in input samples: the delay line drains from
    # the first gate_advance, which is get_dsp_latency() + gate_latency
    # samples in. This is a RESULT of the self-timed wiring, not a knob --
    # nothing in the hardware reads it. It is the number a golden model needs
    # to line raw samples up with gate beats, and the lower bound delay_depth
    # must exceed.
    detect_pulses.get_path_b_delay = lambda: (
        detect_pulses.get_dsp_latency() + detect_pulses.gate_latency
    )
    return detect_pulses, detect_pulses_t
