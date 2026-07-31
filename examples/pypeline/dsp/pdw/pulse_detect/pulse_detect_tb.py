# pyright: reportInvalidTypeForm=none
"""Native-sim testbench for the PDW hysteresis SM / candidate-PDW extractor
(pulse_detect.py). sim_assert (in-hardware) is the pass/fail mechanism, same
convention as pulse_gen_tb.py -- not @sim_input/@sim_output.

Stimulus is a hardware sample-index counter that only advances on `accepted`
(the self_check_stream_pipeline_test.py idiom), so a stalled consumer holds
the presented sample instead of silently dropping it -- required for a
correct elastic-mode backpressure test.

Waveform: a PRI-periodic pulse of width TEST_WIDTH, with a deliberate
mid-pulse DIP down into the [threshold_low, threshold_high) guard band at
DIP_PHASE. A non-hysteretic detector would end the pulse early at the dip and
split it in two -- so `pulse_width == TEST_WIDTH` on every candidate *is* the
hysteresis test.

Checks (see pulse_detect.py's module docstring for why these invariants hold):
  - gate_last never fires without gate_valid the same cycle (the AXIS
    last-without-valid bug this design was built to avoid).
  - gate_valid beats between consecutive gate_last events == TEST_WIDTH,
    AND equals the pulse_width of the candidate arriving that same cycle --
    ties the packet bounds and the metadata to each other.
  - Every candidate: pulse_width == TEST_WIDTH, peak_power == TEST_HIGH_POWER
    (the dip must not become the peak).
  - Spacing between gate_last events == TEST_PRI (measured off the real-time
    edge, not off candidate beats, whose spacing jitters under stuttered
    ready).
  - overflow == 0 every cycle in elastic mode (the 1-deep slot never
    overflows because input ready gates on it).
  - Liveness: a candidate arrives within one PRI + margin.

Run:
    pypelinec examples/pypeline/dsp/pdw/pulse_detect/pulse_detect_tb.py --sim --comb --run 500
"""

from pypeline import MAIN, Reg, sim_assert, uint1_t, uint3_t, uint32_t

from pulse_detect import make_pulse_detect_fsm

from fixed_point import make_fixed_t

# ---------------------------------------------------------------------------
# Shared waveform parameters
# ---------------------------------------------------------------------------
TEST_PRI = 60
TEST_WIDTH = 20
DIP_PHASE = 10  # must be in (0, TEST_WIDTH-1): a mid-pulse sample, not first/last

THRESHOLD_HIGH = 2_500_000
THRESHOLD_LOW = 1_000_000
HIGH_POWER = 3_000_000  # above threshold_high -- the pulse's power level
DIP_POWER = 1_500_000  # inside the guard band: NOT below threshold_low
LOW_POWER = 0  # below threshold_low -- outside the pulse

MAX_WIDTH_NORMAL = 1_000  # well above TEST_WIDTH: never force-terminates
LIVENESS_MARGIN = 40

data_t = make_fixed_t(32, 0, signed=False)  # README's uint32_t power format


# ---------------------------------------------------------------------------
# 1. Elastic handshake, stuttered consumer ready
# ---------------------------------------------------------------------------
pulse_detect_e, pulse_detect_e_t = make_pulse_detect_fsm(data_t)


@MAIN(125.0)
def pulse_detect_elastic_tb():
    sample_index: Reg[uint32_t]
    phase: uint32_t = sample_index % TEST_PRI
    x: uint32_t = HIGH_POWER
    if phase == DIP_PHASE:
        x = DIP_POWER
    elif phase >= TEST_WIDTH:
        x = LOW_POWER

    stream_in_if: pulse_detect_e.in_intrf.stream_t
    stream_in_if.valid = 1
    stream_in_if.data = data_t(val=x)

    stutter: Reg[uint3_t]
    pdw_ready: uint1_t = stutter[0] | stutter[1]  # ready ~3/4 of cycles
    stutter = stutter + 1

    o = pulse_detect_e(
        pulse_detect_e.in_intrf.fwd_t(stream=stream_in_if),
        pulse_detect_e.out_intrf.fb_t(ready=pdw_ready),
        data_t(val=THRESHOLD_HIGH),
        data_t(val=THRESHOLD_LOW),
        MAX_WIDTH_NORMAL,
    )

    accepted: uint1_t = stream_in_if.valid & o.stream_in_if.ready
    if accepted:
        sample_index = sample_index + 1

    sim_assert(o.overflow == 0, "elastic mode: overflow must never assert")

    # AXIS invariant: last never fires without valid the same cycle.
    sim_assert(
        (~o.gate_last) | o.gate_valid,
        "gate_last asserted without gate_valid -- illegal AXIS",
    )

    # Gate packet-length tracking.
    gate_run_len: Reg[uint32_t]
    if o.gate_valid:
        gate_run_len = gate_run_len + 1
    if o.gate_last:
        sim_assert(
            gate_run_len == TEST_WIDTH,
            f"gate packet length wrong: expected {TEST_WIDTH}, got {gate_run_len}",
        )
        gate_run_len = 0

    # gate_last <-> candidate handshake land on the same cycle (by design).
    pdw_fire: uint1_t = o.pdw_out_if.stream.valid & pdw_ready
    if o.gate_last:
        sim_assert(
            pdw_fire, "gate_last fired without a candidate handshake the same cycle"
        )
    if pdw_fire:
        sim_assert(
            o.gate_last, "candidate handshake fired without gate_last the same cycle"
        )
        sim_assert(
            o.pdw_out_if.stream.data.pulse_width == TEST_WIDTH,
            f"pulse_width wrong: expected {TEST_WIDTH}, "
            f"got {o.pdw_out_if.stream.data.pulse_width}",
        )
        sim_assert(
            o.pdw_out_if.stream.data.peak_power.val == HIGH_POWER,
            f"peak_power wrong: expected {HIGH_POWER}, "
            f"got {o.pdw_out_if.stream.data.peak_power.val}",
        )

    # gate_last spacing == TEST_PRI, measured off the real-time edge. Unlike
    # pulse_gen_tb.py's cycles_since_edge (whose first edge coincides with
    # cycle 0, so the counter's own reset value doubles as the "no prior
    # event" sentinel), this design's first gate_last lands well after reset
    # -- so "no prior event" needs its own explicit flag.
    cycles_since_last: Reg[uint32_t]
    seen_gate_last: Reg[uint1_t]
    if o.gate_last:
        if seen_gate_last:
            sim_assert(
                cycles_since_last == TEST_PRI,
                f"gate_last spacing wrong: expected {TEST_PRI}, got {cycles_since_last}",
            )
        seen_gate_last = 1
        cycles_since_last = 1
    else:
        cycles_since_last = cycles_since_last + 1

    # Liveness: never go more than one PRI + margin without a candidate.
    sim_assert(
        cycles_since_last < TEST_PRI + LIVENESS_MARGIN,
        f"pulse_detect stalled: no gate_last within "
        f"{TEST_PRI + LIVENESS_MARGIN} cycles",
    )


# ---------------------------------------------------------------------------
# 2. valid_only input handshake -- same waveform, always-accepting input
# ---------------------------------------------------------------------------
pulse_detect_vo, pulse_detect_vo_t = make_pulse_detect_fsm(data_t, handshake="valid_only")


@MAIN(125.0)
def pulse_detect_valid_only_tb():
    phase: Reg[uint32_t]  # free-running: valid_only can never be held off
    x: uint32_t = HIGH_POWER
    if phase == DIP_PHASE:
        x = DIP_POWER
    elif phase >= TEST_WIDTH:
        x = LOW_POWER

    stream_in_if: pulse_detect_vo.in_stream_t
    stream_in_if.valid = 1
    stream_in_if.data = data_t(val=x)

    o = pulse_detect_vo(
        stream_in_if,
        pulse_detect_vo.out_intrf.fb_t(ready=1),
        data_t(val=THRESHOLD_HIGH),
        data_t(val=THRESHOLD_LOW),
        MAX_WIDTH_NORMAL,
    )

    if phase == (TEST_PRI - 1):
        phase = 0
    else:
        phase = phase + 1

    sim_assert(o.overflow == 0, "valid_only mode: overflow must never assert here")
    sim_assert(
        (~o.gate_last) | o.gate_valid,
        "gate_last asserted without gate_valid -- illegal AXIS",
    )

    gate_run_len: Reg[uint32_t]
    if o.gate_valid:
        gate_run_len = gate_run_len + 1
    if o.gate_last:
        sim_assert(
            gate_run_len == TEST_WIDTH,
            f"gate packet length wrong: expected {TEST_WIDTH}, got {gate_run_len}",
        )
        gate_run_len = 0

    pdw_fire: uint1_t = o.pdw_out_if.stream.valid
    if o.gate_last:
        sim_assert(
            pdw_fire, "gate_last fired without a candidate handshake the same cycle"
        )
    if pdw_fire:
        sim_assert(
            o.gate_last, "candidate handshake fired without gate_last the same cycle"
        )
        sim_assert(
            o.pdw_out_if.stream.data.pulse_width == TEST_WIDTH,
            f"pulse_width wrong: expected {TEST_WIDTH}, "
            f"got {o.pdw_out_if.stream.data.pulse_width}",
        )
        sim_assert(
            o.pdw_out_if.stream.data.peak_power.val == HIGH_POWER,
            f"peak_power wrong: expected {HIGH_POWER}, "
            f"got {o.pdw_out_if.stream.data.peak_power.val}",
        )

    cycles_since_last: Reg[uint32_t]
    seen_gate_last: Reg[uint1_t]
    if o.gate_last:
        if seen_gate_last:
            sim_assert(
                cycles_since_last == TEST_PRI,
                f"gate_last spacing wrong: expected {TEST_PRI}, got {cycles_since_last}",
            )
        seen_gate_last = 1
        cycles_since_last = 1
    else:
        cycles_since_last = cycles_since_last + 1

    sim_assert(
        cycles_since_last < TEST_PRI + LIVENESS_MARGIN,
        f"pulse_detect (valid_only) stalled: no gate_last within "
        f"{TEST_PRI + LIVENESS_MARGIN} cycles",
    )


# ---------------------------------------------------------------------------
# 3. CW / jamming: power permanently above threshold_high, tight max_width.
#    Exactly ONE candidate (width == max_width) should ever appear -- the
#    RECOVER state's reason for existing. Downstream would reject this
#    candidate via its own CW-rejection rule (pulse_width == max_width).
# ---------------------------------------------------------------------------
CW_MAX_WIDTH = 32
pulse_detect_cw, pulse_detect_cw_t = make_pulse_detect_fsm(data_t)


@MAIN(125.0)
def pulse_detect_cw_tb():
    stream_in_if: pulse_detect_cw.in_intrf.stream_t
    stream_in_if.valid = 1
    stream_in_if.data = data_t(val=HIGH_POWER)  # permanently above threshold_high

    o = pulse_detect_cw(
        pulse_detect_cw.in_intrf.fwd_t(stream=stream_in_if),
        pulse_detect_cw.out_intrf.fb_t(ready=1),
        data_t(val=THRESHOLD_HIGH),
        data_t(val=THRESHOLD_LOW),
        CW_MAX_WIDTH,
    )

    sim_assert((~o.gate_last) | o.gate_valid, "gate_last without gate_valid (CW)")

    candidates_seen: Reg[uint32_t]
    if o.pdw_out_if.stream.valid:
        sim_assert(
            candidates_seen == 0,
            f"CW input produced more than one candidate "
            f"(seen {candidates_seen + 1})",
        )
        sim_assert(
            o.pdw_out_if.stream.data.pulse_width == CW_MAX_WIDTH,
            f"CW candidate width wrong: expected {CW_MAX_WIDTH}, "
            f"got {o.pdw_out_if.stream.data.pulse_width}",
        )
        sim_assert(
            o.pdw_out_if.stream.data.peak_power.val == HIGH_POWER,
            f"CW candidate peak wrong: expected {HIGH_POWER}, "
            f"got {o.pdw_out_if.stream.data.peak_power.val}",
        )
        candidates_seen = candidates_seen + 1

    cycles: Reg[uint32_t]
    sim_assert(
        (candidates_seen != 0) | (cycles < CW_MAX_WIDTH + LIVENESS_MARGIN),
        f"CW input never produced a candidate within "
        f"{CW_MAX_WIDTH + LIVENESS_MARGIN} cycles",
    )
    cycles = cycles + 1
