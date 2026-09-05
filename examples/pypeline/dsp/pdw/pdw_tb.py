# pyright: reportInvalidTypeForm=none
"""Top-level native-sim testbench for top.py (see README.md section 5).

Drives top.py's real Input[T] ports -- pulse generator config, detector
thresholds/max_width, pulse_loopback_en -- and checks both of its output
streams (candidate_pdw_*, rx0_m_axis_*) against an exact Python golden model
of the whole chain (pulse_gen -> magnitude -> dc_block -> moving_avg ->
hysteresis FSM -> Path B delay + gate), across a handful of pulse settings,
including settings that must be filtered out entirely (threshold too high,
signal too weak) and one that forces the max_width/CW-cap path.

`pulse_loopback_en` is held at 1 throughout -- this exercises the internal
pulse_gen loopback path, not the external rx0_s_axis_* cable path (a garbage
walking pattern is driven on rx0_s_axis_tdata/tvalid specifically so a broken
loopback mux would show up as a golden-model mismatch, not silently pass).

Style: @sim_input/@sim_output (the only mechanism that can drive a real
top-level Input[T] in native sim -- see src/tests/pypeline_tests/inst/
sim_input_test.py). Only runs under `pypelinec ... --sim --comb --run N`;
@sim_input/@sim_output are invisible to GHDL/cocotb.

Checking follows the wireguard-fpga testbenches' shape (encrypt_tb.py /
decrypt_tb.py): a `Scoreboard` (include/pypeline/axi/axis_sim.py) per output
stream, populated from the golden model at import time, `expect()`ed once and
`check()`ed in arrival order as real output beats show up. Unlike those
testbenches (which only sim_print "ERROR: ..." because their build script
greps the log), `run_all.py` judges purely on process exit code
(src/tests/pypeline_tests/common.py), so every mismatch here prints a rich
diagnostic AND raises AssertionError -- the dsp_tb.py convention.

-----------------------------------------------------------------------------
PATH B ALIGNMENT
-----------------------------------------------------------------------------
This testbench is the acceptance test for Path B's delay line: a packet must
carry exactly the raw I/Q samples whose power produced its own gate beats.
That is a strong check -- it fails on any latency mismatch anywhere in
magnitude -> dc_block -> moving_avg -> FSM, in either direction -- and it is
what caught the delay line only ever realising the FWFT FIFO's incidental
2-cycle latency instead of tracking the DSP chain's real one.

Section 0 below derives the one index relation it rests on, and asserts it
against `detect_pulses.get_path_b_delay()` so that a future change to Path A's
or Path B's wiring fails here with a clear message rather than as opaque
packet-content garbage.

Run:
    pypelinec examples/pypeline/dsp/pdw/pdw_tb.py --sim --comb --run 6200
"""

import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pypeline import MAIN, sim_finish, sim_input, sim_output, sim_print

import top
from dsp.dsp_tb import golden_dc_block, golden_magnitude, golden_moving_avg
from axi.axis_sim import Scoreboard

# ---------------------------------------------------------------------------
# 0. Latency metadata -- read from the instances top.py already built, never
#    hardcoded (see pulse_detect.py's make_detect_pulses / dsp/{magnitude,
#    dc_block,moving_avg}.py's get_latency() accessors).
# ---------------------------------------------------------------------------
_DP = top.detect_pulses
DSP_LAT = _DP.get_dsp_latency()  # magnitude + dc_block + moving_avg, io-regs incl.
GATE_LAT = _DP.gate_latency  # fixed: gate_valid_r <- held_in_pulse
PDW_LAT = _DP.pdw_latency  # fixed: pdw_reg presented-then-drained

# Path B alignment. The gate beat presented at golden-loop index `_s` was
# produced by power sample `_s - GATE_LAT`: _fsm_step returns gate_valid_r as
# it was ON ENTRY, and that value was written at `_s-1` from held_in_pulse as
# IT was on entry, which was written at `_s-2` as in_pulse(power[_s-2]). Two
# register hops. So the raw sample that beat must carry is raw[_s - GATE_LAT],
# and the hardware's Path B delay must be DSP_LAT + GATE_LAT input samples --
# which is exactly what detect_pulses.get_path_b_delay() reports and what the
# self-timed gate_advance drain achieves. Asserted against the hardware's own
# metadata below rather than restated as a literal.
assert _DP.get_path_b_delay() == DSP_LAT + GATE_LAT, (
    f"pdw_tb: detect_pulses.get_path_b_delay() = {_DP.get_path_b_delay()} does "
    f"not match this golden model's assumption of DSP_LAT({DSP_LAT}) + "
    f"GATE_LAT({GATE_LAT}) -- Path B's wiring changed, re-derive raw_idx below"
)
assert _DP.delay_depth > _DP.get_path_b_delay(), (
    f"pdw_tb: delay_depth={_DP.delay_depth} must exceed the Path B hold window "
    f"({_DP.get_path_b_delay()} samples) or the delay line drops pushes"
)


# ---------------------------------------------------------------------------
# 1. Phase schedule
# ---------------------------------------------------------------------------
N_PERIODS = 3  # repetitions of each phase's own pri, back to back
IDLE_MARGIN = 32  # min idle samples after each pulse before the next period
SUPPRESS_THRESHOLD = 4_000_000_000  # < 2**32; see build-time assert below


@dataclass
class Phase:
    name: str
    pri: int
    width: int
    amplitude: int
    max_width: int = 1_000_000  # effectively unbounded unless overridden
    min_width: int = 4  # well below every non-glitch phase's own width
    auto_threshold: bool = True  # False for phases 3/4, which set thr_hi/thr_lo below
    thr_hi: int = 0
    thr_lo: int = 0
    # expect_pdws: Path A must produce a CANDIDATE per period (detection).
    # expect_valid: the engine must ACCEPT it (qualification). The two differ
    # exactly where this testbench is interesting: phases 5 and 6 are detected
    # and then deliberately thrown away by the engine.
    expect_pdws: bool = True
    expect_valid: bool = True


# ORDER MATTERS. A rejected pulse is erased by draining its buffered beats out
# of the store-and-forward FIFO and discarding them (see make_packet_store's
# FLUSH state); if that drain moved the wrong number of beats, the damage
# would only ever show up in the NEXT released packet. So both rejecting
# phases are placed BEFORE a releasing one -- otherwise a flush-count bug
# would leave no evidence anywhere and this testbench would pass regardless.
PHASES = [
    Phase(name="baseline", pri=256, width=64, amplitude=600),
    Phase(name="short pulse (moving_avg edge smear)", pri=192, width=16, amplitude=800),
    # Detected but GLITCH-rejected: min_width is set above anything this
    # pulse's width can smear out to (asserted exactly, below).
    Phase(
        name="glitch (width < min_width)",
        pri=192,
        width=8,
        amplitude=800,
        min_width=24,
        expect_valid=False,
    ),
    # Detected (as a max_width-wide candidate) but CW-rejected by the engine.
    Phase(
        name="CW / max_width cap",
        pri=512,
        width=300,
        amplitude=600,
        max_width=64,
        expect_valid=False,
    ),
    # Released, and deliberately AFTER both rejecting phases -- see above.
    Phase(name="long pulse, different amplitude", pri=384, width=200, amplitude=400),
    Phase(
        name="threshold-suppressed",
        pri=256,
        width=64,
        amplitude=600,
        auto_threshold=False,
        thr_hi=SUPPRESS_THRESHOLD,
        thr_lo=0,
        expect_pdws=False,
        expect_valid=False,
    ),
    Phase(
        name="signal too weak",
        pri=256,
        width=64,
        amplitude=40,
        auto_threshold=False,  # filled in below from "baseline"'s calibrated values
        expect_pdws=False,
        expect_valid=False,
    ),
]

# Phases are referred to by NAME everywhere below, never by literal index, so
# reordering them (which the note above says is load-bearing) cannot silently
# point an assertion at the wrong phase.
PH = {p.name: i for i, p in enumerate(PHASES)}
assert len(PH) == len(PHASES), "phase names must be unique"
P_BASELINE = PH["baseline"]
P_GLITCH = PH["glitch (width < min_width)"]
P_CW = PH["CW / max_width cap"]
P_SUPPRESSED = PH["threshold-suppressed"]
P_WEAK = PH["signal too weak"]
assert P_GLITCH < PH["long pulse, different amplitude"], (
    "the glitch phase must precede a releasing phase -- see the ordering note above"
)
assert P_CW < PH["long pulse, different amplitude"], (
    "the CW phase must precede a releasing phase -- see the ordering note above"
)

for _p in PHASES:
    assert _p.pri >= _p.width + IDLE_MARGIN, (
        f"phase {_p.name!r}: pri={_p.pri} must be >= width({_p.width}) + "
        f"IDLE_MARGIN({IDLE_MARGIN}) so the detector's pipeline drains before "
        f"the next period/phase begins"
    )


# ---------------------------------------------------------------------------
# 2. Golden model, pass 1: stimulus + power sequence
# ---------------------------------------------------------------------------


def _golden_pulse_gen_raw(pri, width, amplitude, n_cycles):
    """Mirrors pulse_gen.py's pulse_gen() exactly (see pulse_gen.py:35-46):
    pri_counter is a free-running mod-pri counter; since every phase's own
    duration is an exact multiple of its own pri (asserted above) and the
    counter starts each phase reading 0 (guaranteed by the previous phase
    ending on a wrap-around cycle), `k % pri` reproduces the counter's value
    at local cycle k with no need to track cross-phase register state."""
    out = []
    for k in range(n_cycles):
        active = (k % pri) < width
        out.append((amplitude if active else 0, 0))  # (i, q); pulse_gen never sets q
    return out


def _nominal_windows(start, pri, width, n_periods):
    """[start, start+width) for each of n_periods periods -- the *intended*
    in-pulse sample ranges, used only to calibrate auto thresholds (the FSM's
    real detected pulse_width can differ by a few samples at the edges due to
    moving_avg's smoothing -- that's fine, expected values below come from
    walking the FSM model, not from these nominal windows)."""
    return [(start + p * pri, start + p * pri + width) for p in range(n_periods)]


raw = []
phase_bounds = []  # (start, end) absolute sample-index range per phase
for _ph in PHASES:
    _start = len(raw)
    raw.extend(_golden_pulse_gen_raw(_ph.pri, _ph.width, _ph.amplitude, N_PERIODS * _ph.pri))
    phase_bounds.append((_start, len(raw)))

TOTAL_SAMPLES = len(raw)

# dc_block's mean is one continuous IIR state across the WHOLE run (a single
# hardware instance, never reset between phases) -- so golden_dc_block must
# see the whole concatenated stimulus in one call, exactly like the hardware.
power = golden_moving_avg(
    _DP.moving_avg, golden_dc_block(_DP.dc_block, golden_magnitude(_DP.magnitude, raw))
)
assert len(power) == TOTAL_SAMPLES

# ---------------------------------------------------------------------------
# 3. Per-phase threshold calibration
# ---------------------------------------------------------------------------
for _i, _ph in enumerate(PHASES):
    if not _ph.auto_threshold:
        continue
    _start, _end = phase_bounds[_i]
    _windows = _nominal_windows(_start, _ph.pri, _ph.width, N_PERIODS)
    _peaks = [max(power[s:e]) for s, e in _windows]
    _min_peak = min(_peaks)
    _ph.thr_hi = int(0.6 * _min_peak)
    _ph.thr_lo = int(0.3 * _min_peak)

# "signal too weak": reuse the baseline phase's calibrated thresholds -- the
# whole point is that its much smaller amplitude must fail to cross a
# threshold that a real pulse does cross.
PHASES[P_WEAK].thr_hi = PHASES[P_BASELINE].thr_hi
PHASES[P_WEAK].thr_lo = PHASES[P_BASELINE].thr_lo

assert SUPPRESS_THRESHOLD < 2**32, "SUPPRESS_THRESHOLD must fit the uint32_t threshold_high port"
for _i, _ph in enumerate(PHASES):
    if _i == P_SUPPRESSED:
        _start, _end = phase_bounds[_i]
        _windows = _nominal_windows(_start, _ph.pri, _ph.width, N_PERIODS)
        _own_peak = max(max(power[s:e]) for s, e in _windows)
        assert SUPPRESS_THRESHOLD > _own_peak, (
            f"SUPPRESS_THRESHOLD ({SUPPRESS_THRESHOLD}) must exceed the "
            f"threshold-suppressed phase's own peak power ({_own_peak}) to "
            f"guarantee suppression"
        )
    assert 0 <= _ph.thr_hi < 2**32 and 0 <= _ph.thr_lo < 2**32, (
        f"phase {_ph.name!r}: thresholds must fit the uint32_t port "
        f"(thr_hi={_ph.thr_hi}, thr_lo={_ph.thr_lo})"
    )

# Per-absolute-sample-index schedules (thresholds are NOT pipelined through
# the DSP chain -- they feed the FSM combinationally -- so the schedule is
# indexed by sample index directly, relying on IDLE_MARGIN to guarantee the
# few cycles of skew around each phase boundary land during genuinely idle
# power, where old-vs-new threshold choice is inconsequential).
thr_hi_sched = []
thr_lo_sched = []
max_width_sched = []
min_width_sched = []
for _ph in PHASES:
    thr_hi_sched.extend([_ph.thr_hi] * (N_PERIODS * _ph.pri))
    thr_lo_sched.extend([_ph.thr_lo] * (N_PERIODS * _ph.pri))
    max_width_sched.extend([_ph.max_width] * (N_PERIODS * _ph.pri))
    min_width_sched.extend([_ph.min_width] * (N_PERIODS * _ph.pri))
assert len(thr_hi_sched) == TOTAL_SAMPLES
assert len(min_width_sched) == TOTAL_SAMPLES


# ---------------------------------------------------------------------------
# 4. Golden model, pass 2: FSM + gate walk (mirrors pulse_detect.py's
#    valid_only pulse_detect_fsm exactly -- see that function's own comments
#    for the register semantics this reproduces).
# ---------------------------------------------------------------------------
def _new_fsm_state():
    return {
        "state": "IDLE",
        "width": 0,
        "peak": 0,
        "pdw_valid": 0,
        "pdw_data": None,
        "held_in_pulse": 0,
        "gate_valid_r": 0,
        "gate_last_r": 0,
        "toa_counter": 0,
        "toa_latch": 0,
        "pdw_pending": 0,
        "pdw_pending_data": None,
    }


def _fsm_step(st, p, thr_hi, thr_lo, max_width):
    """One simulated hardware cycle. Registers are read here as committed
    from the PREVIOUS call (matching hardware's read-before-write Reg
    semantics), and this call's writes become visible on the NEXT call --
    so the returned (pdw_valid, pdw_data, gate_valid, gate_last) values are
    exactly what pulse_detect_fsm's output ports show this cycle."""
    out_pdw_valid, out_pdw_data = st["pdw_valid"], st["pdw_data"]
    out_gate_valid, out_gate_last = st["gate_valid_r"], st["gate_last_r"]

    if st["pdw_valid"]:  # drain (the engine's candidate ready is always 1)
        st["pdw_valid"] = 0

    above_high = p > thr_hi
    below_low = p < thr_lo

    in_pulse = 0
    if st["state"] == "IDLE":
        in_pulse = 1 if above_high else 0
    elif st["state"] == "PULSE":
        in_pulse = 0 if below_low else 1
    # RECOVER -> 0

    st["gate_valid_r"] = st["held_in_pulse"]
    st["gate_last_r"] = 1 if (st["held_in_pulse"] and not in_pulse) else 0
    st["held_in_pulse"] = in_pulse

    if st["pdw_pending"]:  # held CW candidate -- see the force-close below
        st["pdw_data"] = st["pdw_pending_data"]
        st["pdw_valid"] = 1
        st["pdw_pending"] = 0

    if st["state"] == "IDLE":
        if above_high:
            st["state"] = "PULSE"
            st["width"] = 1
            st["peak"] = p
            st["toa_latch"] = st["toa_counter"]  # pre-increment: THIS sample
    elif st["state"] == "PULSE":
        if below_low:
            st["pdw_data"] = (st["toa_latch"], st["width"], st["peak"])
            st["pdw_valid"] = 1
            st["state"] = "IDLE"
        else:
            new_width = st["width"] + 1
            new_peak = p if p > st["peak"] else st["peak"]
            if new_width >= max_width:
                # CW force-close: HELD one accepted sample so the candidate
                # lands on the same cycle as its own gate_last (see
                # pulse_detect.py's force-close branch for the derivation).
                st["pdw_pending_data"] = (st["toa_latch"], new_width, new_peak)
                st["pdw_pending"] = 1
                st["state"] = "RECOVER"
            else:
                st["width"] = new_width
                st["peak"] = new_peak
    else:  # RECOVER
        if below_low:
            st["state"] = "IDLE"

    st["toa_counter"] += 1  # last: every read above is pre-increment

    return out_pdw_valid, out_pdw_data, out_gate_valid, out_gate_last


def _phase_of(sample_idx):
    for i, (s, e) in enumerate(phase_bounds):
        if s <= sample_idx < e:
            return i
    return len(PHASES) - 1


expected_pdws = []  # candidates: (phase_idx, toa, pulse_width, peak_power_u32)
expected_gate_packets = []  # every gate packet: (phase_idx, tuple_of_tdata_words)
# What the ENGINE should let through (README box 3): the accepted subset.
expected_valid_pdws = []  # (phase_idx, toa, width, peak, pkt_samples, status)
expected_released = []  # (phase_idx, tuple_of_tdata_words)
expected_rejects = []  # (phase_idx, "glitch" | "cw") -- for non-vacuity only
first_gate_beat_sample_idx = None

_fsm_st = _new_fsm_state()
_cur_packet = []
for _s in range(TOTAL_SAMPLES):
    pdw_valid, pdw_data, gate_valid, gate_last = _fsm_step(
        _fsm_st, power[_s], thr_hi_sched[_s], thr_lo_sched[_s], max_width_sched[_s]
    )
    if pdw_valid:
        toa, width, peak = pdw_data
        expected_pdws.append((_phase_of(_s), toa, width, peak & 0xFFFFFFFF))
        assert peak < 2**32, (
            f"golden peak_power {peak} exceeds the uint32_t candidate_pdw_peak_power "
            f"port's range -- reduce a phase's amplitude"
        )
    if gate_valid:
        if first_gate_beat_sample_idx is None:
            first_gate_beat_sample_idx = _s
        raw_idx = _s - GATE_LAT  # see the Path B alignment note in section 0
        i_val, q_val = raw[raw_idx] if 0 <= raw_idx < TOTAL_SAMPLES else (0, 0)
        tdata = ((q_val & 0xFFFF) << 16) | (i_val & 0xFFFF)
        _cur_packet.append(tdata)
    if gate_last:
        # gate_last and the candidate's valid land on the SAME cycle by the
        # hysteresis SM's design, so this packet's metadata is the candidate
        # appended just above -- which is exactly the pairing the engine's
        # descriptor construction relies on.
        assert pdw_valid, (
            f"golden model: gate_last at sample {_s} without a coincident "
            f"candidate -- the gate_last/candidate pairing invariant is broken"
        )
        expected_gate_packets.append((_phase_of(_s), tuple(_cur_packet)))

        # --- mirror make_pdw_qualify, then make_packet_store's release path.
        # min_width/max_width are combinational into the engine (not pipelined),
        # so they are indexed by this same sample -- the same reasoning the
        # threshold schedules use above.
        _toa, _width, _peak = pdw_data
        _is_glitch = _width < min_width_sched[_s]
        _is_cw = _width >= max_width_sched[_s]
        if _is_glitch or _is_cw:
            expected_rejects.append((_phase_of(_s), "glitch" if _is_glitch else "cw"))
        else:
            # status_flags is 0 for every packet this testbench produces: no
            # amplitude here reaches the int16 rail (ADC clip), the FSM's
            # overflow cannot set with the engine always ready, and the
            # packet FIFO is far larger than any packet. Asserting 0 is the
            # negative check that no flag sets spuriously; the flags' positive
            # paths are exercised in pdw_engine/pdw_engine_tb.py, where the
            # engine's inputs can be driven directly.
            expected_valid_pdws.append(
                (
                    _phase_of(_s),
                    _toa,
                    _width,
                    _peak & 0xFFFFFFFF,
                    len(_cur_packet),  # pkt_samples == beats pushed
                    0,  # status_flags
                )
            )
            expected_released.append((_phase_of(_s), tuple(_cur_packet)))
        _cur_packet = []

assert first_gate_beat_sample_idx is not None, "golden model produced no gate beats at all"

# ---------------------------------------------------------------------------
# 5. Non-vacuity assertions (build-time, plain Python) -- a config edit that
#    quietly guts the test should fail loudly here, not pass silently.
# ---------------------------------------------------------------------------
for _i, _ph in enumerate(PHASES):
    _n = sum(1 for p, *_ in expected_pdws if p == _i)
    _nv = sum(1 for p, *_ in expected_valid_pdws if p == _i)
    _want = N_PERIODS if _ph.expect_pdws else 0
    assert _n == _want, (
        f"phase {_i} ({_ph.name!r}): expected {_want} CANDIDATE PDWs, golden "
        f"model produced {_n}"
    )
    _want_v = N_PERIODS if (_ph.expect_pdws and _ph.expect_valid) else 0
    assert _nv == _want_v, (
        f"phase {_i} ({_ph.name!r}): expected {_want_v} VALID PDWs, golden "
        f"model produced {_nv}"
    )

# The two rejecting phases must reject for DIFFERENT reasons -- not both by
# accident via the same rule, which would leave one of the two rules untested.
_cw_pdws = [w for p, _t, w, _pk in expected_pdws if p == P_CW]
assert all(w == PHASES[P_CW].max_width for w in _cw_pdws), (
    f"CW phase: expected every pulse_width == {PHASES[P_CW].max_width}, got {_cw_pdws}"
)
assert [r for p, r in expected_rejects if p == P_CW] == ["cw"] * N_PERIODS, (
    f"CW phase must be rejected as CW, got "
    f"{[r for p, r in expected_rejects if p == P_CW]}"
)
_glitch_widths = [w for p, _t, w, _pk in expected_pdws if p == P_GLITCH]
assert all(w < PHASES[P_GLITCH].min_width for w in _glitch_widths), (
    f"glitch phase: every detected width {_glitch_widths} must be below "
    f"min_width={PHASES[P_GLITCH].min_width} -- moving_avg's edge smear widened "
    f"the pulse past the rejection threshold, raise min_width or shorten the pulse"
)
assert [r for p, r in expected_rejects if p == P_GLITCH] == ["glitch"] * N_PERIODS, (
    f"glitch phase must be rejected as a glitch, got "
    f"{[r for p, r in expected_rejects if p == P_GLITCH]}"
)
# ...and every phase that IS expected to pass must not be rejected at all,
# i.e. its own min_width really is below the smeared width.
for _i, _ph in enumerate(PHASES):
    if _ph.expect_pdws and _ph.expect_valid:
        assert not [r for p, r in expected_rejects if p == _i], (
            f"phase {_i} ({_ph.name!r}) was expected to pass qualification but "
            f"the golden model rejected it -- check its min_width/max_width"
        )

assert len(expected_gate_packets) == len(expected_pdws), (
    f"expected_gate_packets ({len(expected_gate_packets)}) and expected_pdws "
    f"({len(expected_pdws)}) must be produced 1:1 by the same FSM walk"
)
assert len(expected_released) == len(expected_valid_pdws), (
    f"expected_released ({len(expected_released)}) and expected_valid_pdws "
    f"({len(expected_valid_pdws)}) must be produced 1:1 by the engine model"
)
assert len(expected_rejects) + len(expected_released) == len(expected_gate_packets), (
    "every gate packet must be either released or rejected, exactly once"
)
for _idx, (_phase_idx, _pkt) in enumerate(expected_gate_packets):
    _width = expected_pdws[_idx][2]
    assert len(_pkt) == _width and len(_pkt) > 0, (
        f"gate packet {_idx} (phase {_phase_idx}): length {len(_pkt)} != "
        f"pulse_width {_width}"
    )
# pkt_samples is the field a DMA consumer sizes its transfer from, so it has
# to match the released beat count exactly, not merely the candidate's width.
for _idx, (_phase_idx, _pkt) in enumerate(expected_released):
    assert len(_pkt) == expected_valid_pdws[_idx][4], (
        f"released packet {_idx} (phase {_phase_idx}): {len(_pkt)} beats != "
        f"pkt_samples {expected_valid_pdws[_idx][4]}"
    )
assert len(expected_released) > 0 and len(expected_rejects) > 0, (
    "this testbench is vacuous unless it produces BOTH released and rejected "
    "packets"
)

TOTAL_CYCLES = TOTAL_SAMPLES
sim_print(
    f"pdw_tb: {len(PHASES)} phases, {TOTAL_SAMPLES} stimulus samples, "
    f"{len(expected_pdws)} candidates -> {len(expected_valid_pdws)} released + "
    f"{len(expected_rejects)} rejected, "
    f"DSP_LAT={DSP_LAT} GATE_LAT={GATE_LAT} PDW_LAT={PDW_LAT} "
    f"path_b_delay={_DP.get_path_b_delay()}"
)


# ---------------------------------------------------------------------------
# 6. Scoreboards
#
# Population is deliberately DEFERRED to the first simulated cycle (see
# _populate_scoreboards() call in drive_stimulus() below), not done here at
# import time. Reason: `_build_reg_sim_func`'s decoration-time introspection
# (`_local_const_ns`, see docs/pypeline_sim_DESIGN.md) speculatively
# `eval()`s any bare `x = f(...)` assignment found in a later @sim_output
# function's body, to resolve local-variable references in Reg[T]/
# Feedback[T] annotations. `check_packet()`'s `result = _pkt_sb.check(got_pkt)`
# is a fully-resolvable plain Python expression (both `_pkt_sb` and
# `got_pkt` are ordinary already-evaluable objects, no wire dependency) --
# so if the scoreboard were already populated at decoration time, that
# speculative eval would silently execute the real check() call as a side
# effect, consuming one real expected entry before the simulation ever runs
# (this is exactly what happened during development: the very first packet
# always came up missing). Deferring population until cycle 0 (well after
# decoration) makes that same speculative probe hit an empty, harmless
# queue instead.
# ---------------------------------------------------------------------------
_pdw_sb = Scoreboard()  # candidate_pdw_*  -- Path A, every detected pulse
_vpdw_sb = Scoreboard()  # valid_pdw_*      -- engine, accepted pulses only
_pkt_sb = Scoreboard()  # rx0_m_axis_*     -- engine, released packets only


def _populate_scoreboards():
    for idx, (phase_idx, toa, width, peak) in enumerate(expected_pdws):
        _pdw_sb.expect((toa, width, peak), phase=phase_idx, idx=idx)
    for idx, exp in enumerate(expected_valid_pdws):
        phase_idx = exp[0]
        _vpdw_sb.expect(tuple(exp[1:]), phase=phase_idx, idx=idx)
    for idx, (phase_idx, pkt) in enumerate(expected_released):
        _pkt_sb.expect(pkt, phase=phase_idx, idx=idx)


# ---------------------------------------------------------------------------
# 7. Drivers + checkers
# ---------------------------------------------------------------------------
# Mutable state shared between @sim_input/@sim_output callbacks, only ever
# mutated in place (never rebound) -- their bodies run against a detached
# snapshot of module globals (docs/pypeline_sim_DESIGN.md), so a rebound
# module-level name would not be visible across calls.
ST = {
    "cycle": 0,
    "announced": False,
    "cur_packet": [],
    "first_beat_cycle": None,
    "alignment_checked": False,
    "n_pdw_done": 0,
    "n_vpdw_done": 0,
    "n_pkt_done": 0,
}

# Backpressure patterns on the two engine output streams. Store-and-forward is
# the whole point of box 3 -- a real-time gate stream feeding a consumer that
# can stall -- so both consumers deliberately stall, on mutually prime periods
# so their stalls drift against each other and against every phase's pri.
# The golden model is unaffected: scoreboards compare content in arrival
# order, and backpressure only changes when beats arrive, never which.
PKT_READY_PERIOD = 5
PDW_READY_PERIOD = 7


@sim_input
def drive_stimulus():
    if ST["cycle"] == 0:
        _populate_scoreboards()
    n = ST["cycle"]
    past_end = n >= TOTAL_SAMPLES
    idx = n if not past_end else TOTAL_SAMPLES - 1
    top.pulse_gen_pri = PHASES[_phase_of(idx)].pri
    top.pulse_gen_width = PHASES[_phase_of(idx)].width
    # Amplitude drops to 0 once the scheduled stimulus is over. The last phase
    # ends exactly on a pri boundary, so leaving it running would start a
    # further pulse the golden model never modelled -- and the engine's
    # store-and-forward latency means this testbench is still draining then.
    top.pulse_gen_amplitude = 0 if past_end else PHASES[_phase_of(idx)].amplitude
    top.threshold_high = thr_hi_sched[idx]
    top.threshold_low = thr_lo_sched[idx]
    top.max_width = max_width_sched[idx]
    top.min_width = min_width_sched[idx]
    top.pulse_loopback_en = 1
    top.rx0_m_axis_tready = 0 if (n % PKT_READY_PERIOD) == 0 else 1
    top.valid_pdw_ready = 0 if (n % PDW_READY_PERIOD) == 0 else 1
    # Deliberately wrong data on the unselected mux leg: if pulse_loopback_en
    # ever failed to select pulse_gen's own sample, this garbage would flow
    # through instead and fail the golden comparison loudly.
    top.rx0_s_axis_tdata = (0xDEAD0000 + (n & 0xFFFF)) & 0xFFFFFFFF
    top.rx0_s_axis_tvalid = 1
    ST["cycle"] = n + 1


@sim_output
def announce():
    if not ST["announced"]:
        ST["announced"] = True
        sim_print("=== pdw_tb: top-level PDW pipeline testbench ===")
        for _i, _ph in enumerate(PHASES):
            sim_print(
                f"  phase {_i} ({_ph.name}): pri={_ph.pri} width={_ph.width} "
                f"amp={_ph.amplitude} thr_hi={_ph.thr_hi} thr_lo={_ph.thr_lo} "
                f"min_width={_ph.min_width} max_width={_ph.max_width} "
                f"-> {'RELEASED' if _ph.expect_valid and _ph.expect_pdws else 'none'}"
            )


@sim_output
def check_pdw():
    if not int(top.candidate_pdw_valid):
        return
    got = (
        int(top.candidate_pdw_toa),
        int(top.candidate_pdw_pulse_width),
        int(top.candidate_pdw_peak_power),
    )
    result = _pdw_sb.check(got)
    idx = result.get("idx", "?")
    phase = result.get("phase", "?")
    if not result["passed"]:
        if "error" in result:
            sim_print(f"ERROR: pdw_tb: {result['error']} (candidate {idx}, phase {phase})")
            raise AssertionError(f"pdw_tb: {result['error']} (candidate {idx})")
        exp, got_v = result["expected"], result["got"]
        sim_print(
            f"ERROR: pdw_tb: candidate {idx} (phase {phase}) mismatch: "
            f"expected toa={exp[0]} width={exp[1]} peak={exp[2]}, "
            f"got toa={got_v[0]} width={got_v[1]} peak={got_v[2]}"
        )
        raise AssertionError(
            f"pdw_tb: candidate {idx} (phase {phase}): expected {exp}, got {got_v}"
        )
    sim_print(
        f"pdw_tb: candidate {idx} (phase {phase}) OK: toa={got[0]} width={got[1]} "
        f"peak={got[2]}"
    )
    ST["n_pdw_done"] += 1


@sim_output
def check_valid_pdw():
    """README box 3's metadata output: only ACCEPTED pulses, and each one must
    arrive BEFORE its own released packet (the ordering a DMA consumer needs
    to size the transfer that follows) -- checked against n_pkt_done below."""
    if not int(top.valid_pdw_valid):
        return
    if not int(top.valid_pdw_ready):
        return  # held, not transferred -- no handshake, nothing to check yet
    got = (
        int(top.valid_pdw_toa),
        int(top.valid_pdw_pulse_width),
        int(top.valid_pdw_peak_power),
        int(top.valid_pdw_pkt_samples),
        int(top.valid_pdw_status_flags),
    )
    result = _vpdw_sb.check(got)
    idx = result.get("idx", "?")
    phase = result.get("phase", "?")
    if not result["passed"]:
        if "error" in result:
            sim_print(f"ERROR: pdw_tb: {result['error']} (valid_pdw {idx}, phase {phase})")
            raise AssertionError(f"pdw_tb: {result['error']} (valid_pdw {idx})")
        exp, got_v = result["expected"], result["got"]
        sim_print(
            f"ERROR: pdw_tb: valid_pdw {idx} (phase {phase}) mismatch: "
            f"expected (toa,width,peak,pkt_samples,status)={exp}, got {got_v}"
        )
        raise AssertionError(
            f"pdw_tb: valid_pdw {idx} (phase {phase}): expected {exp}, got {got_v}"
        )
    assert ST["n_vpdw_done"] == ST["n_pkt_done"], (
        f"pdw_tb: valid_pdw {idx} arrived out of order -- "
        f"{ST['n_vpdw_done']} PDWs vs {ST['n_pkt_done']} packets already done; "
        f"each PDW must be emitted before its own packet, and no two PDWs may "
        f"be emitted back to back without the first one's packet in between"
    )
    sim_print(
        f"pdw_tb: valid_pdw {idx} (phase {phase}) OK: toa={got[0]} width={got[1]} "
        f"peak={got[2]} pkt_samples={got[3]} status=0x{got[4]:04x}"
    )
    ST["n_vpdw_done"] += 1


@sim_output
def check_packet():
    """README box 3's payload output: only RELEASED packets. A rejected pulse
    (glitch or CW) must produce no beats here at all -- which the scoreboard
    enforces implicitly, since the very next released packet's contents would
    not line up if a rejected one had leaked through."""
    transferred = int(top.rx0_m_axis_tvalid) and int(top.rx0_m_axis_tready)
    if transferred:
        if ST["first_beat_cycle"] is None:
            # ST["cycle"] has already been advanced past this cycle by
            # drive_stimulus() (which runs before this checker within the
            # same clock cycle), so the cycle this beat landed on is
            # ST["cycle"] - 1.
            ST["first_beat_cycle"] = ST["cycle"] - 1
        ST["cur_packet"].append(int(top.rx0_m_axis_tdata))
    if int(top.rx0_m_axis_tlast) and not int(top.rx0_m_axis_tvalid):
        raise AssertionError("pdw_tb: rx0_m_axis_tlast asserted without tvalid -- illegal AXIS")
    if not (transferred and int(top.rx0_m_axis_tlast)):
        return
    got_pkt = tuple(ST["cur_packet"])
    ST["cur_packet"] = []
    result = _pkt_sb.check(got_pkt)
    idx = result.get("idx", "?")
    phase = result.get("phase", "?")

    if not ST["alignment_checked"]:
        # Sanity band on Path A/B alignment. The exact-cycle form this used to
        # be no longer applies: rx0_m_axis_* is now the engine's RELEASED
        # stream, so a beat's arrival cycle also carries the store-and-forward
        # buffering delay and the consumer's backpressure. A released beat can
        # still never arrive before the earliest cycle Path A could have
        # produced a gate beat at all, so a gross latency error trips here
        # with a clear message; the fine-grained check is the content
        # comparison below, which is exact to the sample.
        ST["alignment_checked"] = True
        earliest = first_gate_beat_sample_idx + DSP_LAT
        actual_cycle = ST["first_beat_cycle"]
        assert actual_cycle >= earliest, (
            f"pdw_tb: first released beat landed at cycle {actual_cycle}, before "
            f"the earliest cycle Path A could produce a gate beat "
            f"({first_gate_beat_sample_idx} + DSP_LAT {DSP_LAT} = {earliest}) -- "
            f"a latency assumption (DSP_LAT/GATE_LAT) is wrong"
        )

    if not result["passed"]:
        if "error" in result:
            sim_print(f"ERROR: pdw_tb: {result['error']} (packet {idx}, phase {phase})")
            raise AssertionError(f"pdw_tb: {result['error']} (packet {idx})")
        exp, got_v = result["expected"], result["got"]
        n = min(len(exp), len(got_v))
        first_diff = next((i for i in range(n) if exp[i] != got_v[i]), n)
        sim_print(
            f"ERROR: pdw_tb: packet {idx} (phase {phase}) mismatch: "
            f"expected {len(exp)} beats got {len(got_v)} beats, "
            f"first differing beat[{first_diff}]: "
            f"expected 0x{exp[first_diff] if first_diff < len(exp) else -1:08x} "
            f"got 0x{got_v[first_diff] if first_diff < len(got_v) else -1:08x}"
        )
        raise AssertionError(f"pdw_tb: packet {idx} (phase {phase}) mismatch")
    sim_print(f"pdw_tb: packet {idx} (phase {phase}) OK: {len(got_pkt)} beats")
    ST["n_pkt_done"] += 1


@sim_output
def check_done():
    # Generous: the release path is rate-limited by both consumers' stutter
    # (see PKT_READY_PERIOD/PDW_READY_PERIOD) on top of the DSP pipeline's own
    # fill, so this is a liveness backstop, not a tight bound.
    deadline = TOTAL_CYCLES + DSP_LAT + GATE_LAT + 1024
    all_done = (
        _pdw_sb.pending() == 0 and _vpdw_sb.pending() == 0 and _pkt_sb.pending() == 0
    )
    if ST["cycle"] >= TOTAL_CYCLES and all_done:
        # A rejected pulse leaves no trace on either engine output, so
        # "released == expected" alone cannot prove nothing extra leaked
        # through. Assert the counts directly.
        assert ST["n_pkt_done"] == len(expected_released), (
            f"pdw_tb: released {ST['n_pkt_done']} packets, expected "
            f"{len(expected_released)}"
        )
        assert ST["n_vpdw_done"] == len(expected_valid_pdws), (
            f"pdw_tb: emitted {ST['n_vpdw_done']} valid PDWs, expected "
            f"{len(expected_valid_pdws)}"
        )
        assert not int(top.pkt_fifo_full), (
            "pdw_tb: the store-and-forward FIFO overflowed at some point -- "
            "packets were corrupted; increase pdw_engine's depth"
        )
        sim_print(
            f"pdw_tb: {ST['n_pdw_done']} candidates detected, "
            f"{ST['n_vpdw_done']} released with packets, "
            f"{len(expected_rejects)} rejected "
            f"({sum(1 for _p, r in expected_rejects if r == 'glitch')} glitch, "
            f"{sum(1 for _p, r in expected_rejects if r == 'cw')} CW) "
            f"-- Test DONE!"
        )
        sim_finish()
    assert ST["cycle"] < deadline, (
        f"pdw_tb: not done after {ST['cycle']} cycles "
        f"({ST['n_pdw_done']}/{len(expected_pdws)} candidates, "
        f"{ST['n_vpdw_done']}/{len(expected_valid_pdws)} valid PDWs, "
        f"{ST['n_pkt_done']}/{len(expected_released)} released packets)"
    )


@MAIN(125.0)
def pdw_tb_main():
    drive_stimulus()
    announce()
    check_pdw()
    check_valid_pdw()
    check_packet()
    check_done()
