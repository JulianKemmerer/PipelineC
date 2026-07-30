# pyright: reportInvalidTypeForm=none
"""Hysteresis SM + Extract Candidate PDW -- steps 3-4 of Path A ("Detect &
Measure") in the AIR7310 PDW pipeline (see ../README.md). Consumes the
conditioned power stream out of dsp/dc_block.py + dsp/moving_avg.py and
produces:

  1. A valid/ready `candidate_pdw_t{pulse_width, peak_power}` per detected
     pulse (a raw, unvalidated guess -- glitch/CW rejection against
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
the downstream engine rejects it by seeing pulse_width == max_width.

Why the gate stream is delayed one accepted sample: AXIS requires `last` to be
asserted ON the final valid beat, but a sample is only known to be the pulse's
last one once the NEXT sample falls below threshold_low (a one-sample
lookahead). So gate_valid/gate_last are registered one accepted sample behind
the power stream -- gate_last coincides with the final gate_valid beat instead
of trailing it by a cycle (which would be illegal AXIS: last-without-valid).
Convenient consequence: gate_last and the candidate stream's valid land on the
SAME cycle, so a consumer sees the packet's end marker and its metadata
together. This makes the gate path's latency 2 relative to the input sample
(vs. 1 for the candidate) -- worth pinning down once Path B's delay-line FIFO
is sized, since the README's L_sm placeholder is 1.

This is a genuine recurrence (state/width/peak each depend on their own
previous value), so it is NOT run through AUTOPIPELINE/make_stream_pipeline
like the pure feedforward dsp/ blocks -- the same inherent limit dc_block.py
documents for its IIR loop. The critical path is one compare feeding a mux, so
this isn't expected to need it; if it ever misses timing, above_high/below_low
are pure feedforward and can be moved into an autopipelined comparator stage
ahead of the FSM.

TODOs, all owned by Path B / the storage engine, not this block:
  - toa: uint64_t (README: NOT IMPLEMENTED in v1) -- would be a free-running
    125 MHz counter sampled on the IDLE->PULSE edge.
  - gate_ready / backpressure on the gate stream: the SM is real-time and
    cannot stall, so a not-ready storage FIFO means dropped samples (the
    README's status_flags "Packet FIFO Full" bit). When Path B lands,
    gate_valid/gate_last + a new gate_ready arg become one paired stream
    interface (or an axi.make_axis_t stream carrying Path B's tdata).
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
    struct,
    uint1_t,
    uint32_t,
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

    The returned `pulse_detect_fsm` carries metadata attributes:
    .data_t .width_t .candidate_pdw_t .state_t .handshake
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
        # TODO toa: uint64_t -- README marks NOT IMPLEMENTED in v1. Would be
        # a free-running 125 MHz counter sampled on the IDLE->PULSE edge.
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

            if accepted:
                gate_valid_r = held_in_pulse
                gate_last_r = held_in_pulse & ~in_pulse  # prev sample was final
                held_in_pulse = in_pulse

                if state == state_t.IDLE:
                    if above_high:
                        state = state_t.PULSE
                        width = 1  # this sample counts
                        peak = p
                elif state == state_t.PULSE:
                    if below_low:
                        # Terminating sample NOT counted in pulse_width.
                        if pdw_reg.valid:
                            overflow = 1  # unreachable in elastic mode
                        pdw_reg.data = candidate_pdw_t(width, data_t(val=peak))
                        pdw_reg.valid = 1
                        state = state_t.IDLE
                    else:
                        new_width: width_t = width + 1
                        new_peak: data_val_t = p if p > peak else peak
                        if new_width >= max_width:
                            if pdw_reg.valid:
                                overflow = 1  # unreachable in elastic mode
                            pdw_reg.data = candidate_pdw_t(
                                new_width, data_t(val=new_peak)
                            )
                            pdw_reg.valid = 1
                            state = state_t.RECOVER
                        else:
                            width = new_width
                            peak = new_peak
                else:  # RECOVER
                    if below_low:
                        state = state_t.IDLE  # re-arm; one CW -> one candidate
            else:
                gate_valid_r = 0  # no gate beat this cycle
                gate_last_r = 0

            o.overflow = overflow  # last, so it reads post-update
            return o

    elif handshake == "valid_only":
        in_stream_t = make_stream_t(data_t)

        @struct
        class pulse_detect_fsm_t(NamedTuple):
            pdw_out_if: out_intrf.fwd_t  # output port's feedforward half travels out
            gate_valid: uint1_t
            gate_last: uint1_t
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

            if accepted:
                gate_valid_r = held_in_pulse
                gate_last_r = held_in_pulse & ~in_pulse
                held_in_pulse = in_pulse

                if state == state_t.IDLE:
                    if above_high:
                        state = state_t.PULSE
                        width = 1
                        peak = p
                elif state == state_t.PULSE:
                    if below_low:
                        if pdw_reg.valid:
                            overflow = 1  # reachable: input can't be stalled
                        pdw_reg.data = candidate_pdw_t(width, data_t(val=peak))
                        pdw_reg.valid = 1
                        state = state_t.IDLE
                    else:
                        new_width: width_t = width + 1
                        new_peak: data_val_t = p if p > peak else peak
                        if new_width >= max_width:
                            if pdw_reg.valid:
                                overflow = 1
                            pdw_reg.data = candidate_pdw_t(
                                new_width, data_t(val=new_peak)
                            )
                            pdw_reg.valid = 1
                            state = state_t.RECOVER
                        else:
                            width = new_width
                            peak = new_peak
                else:  # RECOVER
                    if below_low:
                        state = state_t.IDLE
            else:
                gate_valid_r = 0
                gate_last_r = 0

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
    pulse_detect_fsm.in_fwd_t = in_intrf.fwd_t if handshake == "elastic" else None
    pulse_detect_fsm.in_stream_t = in_stream_t if handshake == "valid_only" else None
    pulse_detect_fsm.out_fwd_t = out_intrf.fwd_t
    pulse_detect_fsm.out_stream_t = None
    pulse_detect_fsm.in_fb_t = in_intrf.fb_t if handshake == "elastic" else None
    pulse_detect_fsm.out_fb_t = out_intrf.fb_t
    pulse_detect_fsm.in_intrf = in_intrf if handshake == "elastic" else None
    pulse_detect_fsm.out_intrf = out_intrf
    return pulse_detect_fsm, pulse_detect_fsm_t


def make_delay_line(data_t, depth=32):
    """Path B: DELAY LINE FIFO. Returns (delay_line, data_t) (output type same
    as input -- this only delays, it doesn't transform).

    Delays the raw sample stream by a fixed `depth` cycles: make_fifo pushed
    and drained every cycle (always-valid input, always-ready drain) turns
    the FWFT FIFO into an exact fixed-latency delay line, not a
    variable-occupancy queue -- matching the README's Path B description
    (raw I/Q shifted to match Path A's compute latency + N_pre margin).

    depth: delay-line depth in cycles; must be sized (by the caller) to match
    Path A's actual measured latency + N_pre margin once AUTOPIPELINE's real
    latency numbers exist (see README section 3) -- today a placeholder
    supplied explicitly by the caller, no auto-sizing yet.
    """
    fifo_func, _fifo_t = make_fifo(data_t, depth)

    @hw_func
    def delay_line(sample_in: data_t) -> data_t:
        f = fifo_func(1, sample_in, 1)  # always push, always drain -> fixed delay
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


def make_detect_pulses(rail_t=None, dc_k=10, ma_n=4, width_t=uint32_t, delay_depth=32):
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
    delayed by a fixed-depth Path B delay line (see make_delay_line) -- with
    the FSM's real-time gate_valid/gate_last. NOTE: true sample-accurate
    alignment between the delay line's fixed `delay_depth` and the FSM's real
    measured latency (gate stream trails the input sample by 2 cycles per
    make_pulse_detect_fsm's own docstring) is a TODO owned by the storage
    engine / README section 3's FIFO-sizing pass, not solved here -- the
    storage engine is still unbuilt.

    `dc_block.out_t`/`moving_avg.out_t` are full precision (no out_t= passed
    anywhere in the chain), so threshold_high/threshold_low/peak_power are
    typed as `detect_pulses.power_t` (== moving_avg.out_t), NOT a fixed
    README-shaped uint32_t/make_fixed_t(32, 0) -- unlike
    pulse_detect_synth_top.py, which hardcodes that type for the bare
    hysteresis-SM-only block.

    The returned `detect_pulses` carries metadata attributes:
    .rail_t .complex_t .power_t .width_t .candidate_pdw_t .gated_sample_t
    .delay_depth .in_stream_t .out_fb_t .out_fwd_t
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
        delayed_sample = delay_line(stream_in_if.data)
        gate_o = pdw_gate(delayed_sample, pd_o.gate_valid, pd_o.gate_last)

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
    return detect_pulses, detect_pulses_t
