# pyright: reportInvalidTypeForm=none
"""Top-level native-sim testbench for top.py (see README.md section 5).

Every top-level port of top.py is a flattened 32-bit AXI-Stream, so this
testbench speaks AXIS in both directions: it WRITES the control registers as a
framed `pdw_ctrl_t` struct on tx0_s_axis_*, and READS three master streams --
released packets (rx0_m_axis_*), PDW records (rx1_m_axis_*) and candidate
records (rx2_m_axis_*) -- checking each against an exact Python golden model of
the whole chain (pulse_gen -> magnitude -> dc_block -> moving_avg -> hysteresis
FSM -> Path B delay + gate -> measurement -> engine), across a handful of pulse
settings, including settings that must be filtered out entirely (threshold too
high, signal too weak) and one that forces the max_width/CW-cap path.

Framing is done with the library helpers rather than by hand: `type_to_bytes` /
`type_from_bytes` produce the same bytes the hardware serializers do (that is
the point of them), and `AxisSimSource` / `AxisSimSink` handle the beat-level
protocol -- the sink additionally enforces Xilinx-style tkeep compliance on
every beat it accepts, which is free coverage of top.py's constant-keep sample
ports.

CONTROL TIMING. Control values are no longer present on every cycle; they take
effect `pdw_ctrl.latency` cycles after their frame's last beat is accepted.
Rather than assume that, this testbench:
  * sends each phase's frame so it lands exactly on that phase's first sample,
    computed from `pdw_ctrl.n_beats`/`.latency` (never hardcoded);
  * ASSERTS the final beat handshake actually happened on the predicted cycle,
    so a regression in the control path fails loudly here instead of silently
    skewing every downstream expectation;
  * asserts every frame lands in a window the golden model says is idle, so a
    future phase edit cannot reconfigure the generator mid-pulse.
RESET, AND WHY THERE IS NO PRE-ROLL. The design has two reset domains: the
control register file follows `tx0_s_axis_rst` alone, everything else the OR of
all seven channel resets. So this testbench does what a real host should --
release the control channel, write phase 0's configuration while the datapath is
still held, then release the rest. The detector's FIRST sample is therefore
already measured against real thresholds, and there is no default-configured
window left for the golden model to reproduce: `golden_pulse_gen` starts at the
first out-of-reset cycle with the generator's LFSRs at their seeds, exactly as
the hardware does.

Two things are checked about reset itself (see `check_reset`): a POISON frame
sent at cycle 0, entirely inside the control reset, must be decoded and thrown
away; and phase 0's values must be live by `RST_RELEASE`. The second is the one
that matters -- without it the two reset domains could quietly collapse into one
and only surface as a golden mismatch thousands of cycles later.

`pulse_loopback_en` is set from phase 0's frame onward -- this exercises the
internal pulse_gen loopback path, not the external rx0_s_axis_* cable path (a
garbage walking pattern is driven on rx0_s_axis_tdata specifically so a broken
loopback mux would show up as a golden-model mismatch, not silently pass).

Style: @sim_input/@sim_output (the only mechanism that can drive a real
top-level Input[T] in native sim -- see src/tests/pypeline_tests/inst/
sim_input_test.py). Only runs under `pypelinec ... --sim --comb --run N`;
@sim_input/@sim_output are invisible to GHDL/cocotb.

Checking follows the wireguard-fpga testbenches' shape (encrypt_tb.py /
decrypt_tb.py): a `Scoreboard` (include/pypeline/axi/axis_sim.py) per output
stream, populated from the golden model at import time, `expect()`ed once and
`check()`ed in arrival order as real frames show up. Unlike those testbenches
(which only sim_print "ERROR: ..." because their build script greps the log),
`run_all.py` judges purely on process exit code
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
    pypelinec examples/pypeline/dsp/pdw/pdw_tb.py --sim --comb --run 9200
"""

import os
import struct as _pystruct
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pypeline import (
    MAIN,
    byte_length,
    sim_finish,
    sim_input,
    sim_output,
    sim_print,
    type_from_bytes,
    type_to_bytes,
)

import gr_pdw_record
import top
from dsp.dsp_tb import golden_dc_block, golden_magnitude, golden_moving_avg
from pulse_gen import golden_pulse_gen
from pdw_measure import golden_pdw_measure
from pdw_ctrl import CTRL_FLAG_LOOPBACK_EN, pdw_ctrl_t
from pdw_engine import (
    STATUS_FREQ_DEGENERATE,
    STATUS_PKT_FIFO_FULL,
    STATUS_PRI_INVALID,
)
from axi.axis_sim import AxisSimSink, AxisSimSource, Scoreboard

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
# 0b. AXIS boundary: control frame timing, and flat <-> word adapters.
# ---------------------------------------------------------------------------
AXIS_N = top.AXIS_N
_CTRL = top.pdw_ctrl
CTRL_BEATS = _CTRL.n_beats  # 40 bytes / 4 lanes = 10
CTRL_LAT = _CTRL.latency  # last beat accepted -> registers readable

# A frame whose first beat is driven on cycle S occupies S .. S+CTRL_BEATS-1
# (control is never back-pressured, which test_ready_is_always_high in
# pdw_ctrl_test.py is what pins), so its values are live from:
CTRL_APPLY_OFFSET = CTRL_BEATS - 1 + CTRL_LAT

# ---- reset, and the staged bring-up it exists for -------------------------
# The design has two reset domains (see top.py's rst_main): the control
# register file follows tx0_s_axis_rst alone, everything else follows the OR of
# all seven. That is what lets this schedule configure the device BEFORE the
# datapath starts, which is the sequence a real host should use:
#
#   0                     all seven asserted -- held, and buffers drain
#   CTRL_RST_HOLD         tx0_s_axis_rst drops; ctrl block live one cycle later
#   CTRL_FRAME0_AT        phase 0's frame goes out, datapath still held
#   RST_HOLD              the remaining six drop
#   RST_RELEASE           sample 0 -- the detector's FIRST sample is already
#                         measured against phase 0's real thresholds
#
# A POISON frame goes out at cycle 0, entirely inside the control reset, and
# must NOT apply -- check_reset asserts that, and asserts the positive half too
# (phase 0's values ARE live by RST_RELEASE).
#
# Everything here is derived, not hardcoded: change pdw_ctrl.latency or the
# beat count and the whole schedule moves with it.
CTRL_RST_HOLD = CTRL_APPLY_OFFSET + 4  # room for the poison frame to be refused
CTRL_FRAME0_AT = CTRL_RST_HOLD + top.RST_LATENCY
# Sample 0, and the cycle phase 0's write becomes live -- the same cycle, which
# is exactly what _ctrl_frame_start means by "live on the cycle this sample
# enters the detector". RST_HOLD is then derived backwards from it.
RST_RELEASE = CTRL_FRAME0_AT + CTRL_APPLY_OFFSET
RST_HOLD = RST_RELEASE - top.RST_LATENCY

# Cycles before sample 0. Unlike the pre-AXIS-reset version there is no
# "default-configured" window left to model: the generator is reset too, so it
# leaves reset with its LFSRs at their seeds, an empty CORDIC pipeline and phase
# 0's real config already loaded. The golden model's first cycle IS the
# hardware's first out-of-reset cycle.
PRE_ROLL = RST_RELEASE


def _ctrl_frame_start(sample_idx):
    """Cycle on which to drive a frame's first beat so its values are live on
    exactly the cycle sample `sample_idx` enters the detector."""
    return PRE_ROLL + sample_idx - CTRL_APPLY_OFFSET


assert _ctrl_frame_start(0) == CTRL_FRAME0_AT, (
    f"pdw_tb: phase 0's frame would start at {_ctrl_frame_start(0)}, not at "
    f"CTRL_FRAME0_AT={CTRL_FRAME0_AT} -- the reset schedule and the control "
    "schedule have drifted apart"
)
assert CTRL_FRAME0_AT + CTRL_APPLY_OFFSET <= RST_RELEASE, (
    "pdw_tb: phase 0's frame is not live by the time the datapath leaves reset"
)
assert CTRL_FRAME0_AT > CTRL_RST_HOLD, (
    "pdw_tb: phase 0's frame would start while the control block is still in "
    "reset, so it would be discarded along with the poison frame"
)


def _axis_flat(word, n=AXIS_N):
    """(tdata, tkeep, tlast, tvalid) from an AxisSimSource's interface word."""
    d = word.stream.data.frag.data
    k = word.stream.data.frag.keep
    tdata = 0
    tkeep = 0
    for i in range(n):
        tdata |= (int(d[i]) & 0xFF) << (8 * i)
        tkeep |= (int(k[i]) & 1) << i
    return tdata, tkeep, int(word.stream.data.eod[0]), int(word.stream.valid)


def _axis_word(intrf, tdata, tkeep, tlast, transferred, n=AXIS_N):
    """An interface word for AxisSimSink, built from flat output ports.

    `transferred` (tvalid AND tready), not tvalid: AxisSimSink assumes its own
    ready is always 1 and records every valid beat it is shown, so a held beat
    handed to it would be counted twice."""
    frag_t = intrf.stream_t.typeof("data")
    bus_t = frag_t.typeof("frag")
    return intrf.fwd_t(
        intrf.stream_t(
            data=frag_t(
                frag=bus_t(
                    data=[(tdata >> (8 * i)) & 0xFF for i in range(n)],
                    keep=[(tkeep >> i) & 1 for i in range(n)],
                ),
                eod=[tlast],
            ),
            valid=transferred,
        )
    )


# ---------------------------------------------------------------------------
# 1. Phase schedule
# ---------------------------------------------------------------------------
N_PERIODS = 3  # repetitions of each phase's own pri, back to back
# Min idle samples after each pulse before the next period. Must also cover
# the generator's own NCO pipeline latency, since a phase's settings take
# GEN_LAT cycles to reach its output and the boundary skew has to land in
# genuinely idle signal.
IDLE_MARGIN = 64
SUPPRESS_THRESHOLD = 4_000_000_000  # < 2**32; see build-time assert below

# Carrier settings, in pulse_gen's turns x 2^32 phase-increment units.
FS_OVER_8 = 1 << 29  # 0.125 turns/sample
# The chirp sweeps from ~fs/16 upward. Over a 192-sample pulse the increment
# grows by 192 * CHIRP_RATE, which must stay well inside +-0.5 turns/sample
# (Nyquist) or the tone aliases and the "start != stop" check becomes a lie.
CHIRP_START_FREQ = 1 << 28  # 0.0625 turns/sample
CHIRP_RATE = 1 << 21
assert abs(CHIRP_START_FREQ + 192 * CHIRP_RATE) < (1 << 31), (
    "the chirp must not sweep past Nyquist within its pulse"
)


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
    # Carrier controls (see pulse_gen.py). `freq` is the phase increment per
    # sample in turns x 2^32; `chirp_rate` ramps it within a pulse, which is
    # the only way to make freq_start differ from freq_stop; `noise_amp`
    # scales the deterministic LFSR noise.
    freq: int = 0
    chirp_rate: int = 0
    noise_amp: int = 0
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
    # A carrier at fs/8 (2^32 / 8). Every phase that is meant to be DETECTED
    # carries a tone -- a 0 Hz stimulus would let a broken frequency estimator
    # pass, since atan2 of a real-only phasor is 0 whatever the sign
    # conventions are.
    Phase(name="baseline", pri=256, width=64, amplitude=600, freq=FS_OVER_8),
    Phase(
        name="short pulse (moving_avg edge smear)",
        pri=192,
        width=16,
        amplitude=800,
        freq=-FS_OVER_8,  # negative frequency: catches a sign-flipped atan2
    ),
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
    Phase(
        name="long pulse, different amplitude",
        pri=384,
        width=200,
        amplitude=400,
        freq=FS_OVER_8 // 2,
    ),
    # LINEAR FM CHIRP. The only phase where freq_start and freq_stop must
    # DIFFER, which is the only way to test the stop-frequency measurement at
    # all: for every other phase a stop-frequency implementation that simply
    # returned the start frequency would pass.
    Phase(
        name="LFM chirp",
        pri=384,
        width=192,
        amplitude=600,
        freq=CHIRP_START_FREQ,
        chirp_rate=CHIRP_RATE,
        # A real noise floor, so noise_power_db measures something rather than
        # the log converter's zero-input floor. The LFSR's peak excursion is
        # +-(512*noise_amp >> 8), so 8 gives +-16 against an amplitude of 600.
        #
        # It lives on THIS phase, not an earlier one, and that is not
        # arbitrary. dc_block's running mean carries across phases, so the
        # first pulse after a change in signal level is measured against a mean
        # still settling from the previous phase -- its dc-blocked power comes
        # out several times lower than its siblings'. Adding noise on top of
        # that is what pushes it below threshold_low mid-pulse, and the
        # hysteresis SM then (correctly) reports one pulse as several. This
        # phase's own three peaks agree to ~12%, so it has the headroom.
        noise_amp=8,
    ),
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


# The generator's output trails its control inputs by the NCO pipeline depth
# (the pulse envelope is applied as the CORDIC's seed amplitude -- see
# pulse_gen.py). Read it from the hardware rather than writing a number.
GEN_LAT = top.pulse_gen.latency


def _nominal_windows(start, pri, width, n_periods):
    """[start, start+width) for each of n_periods periods -- the *intended*
    in-pulse sample ranges, used only to calibrate auto thresholds (the FSM's
    real detected pulse_width can differ by a few samples at the edges due to
    moving_avg's smoothing -- that's fine, expected values below come from
    walking the FSM model, not from these nominal windows).

    Shifted by GEN_LAT: the generator's PRI counter reaches p*pri at cycle
    p*pri, but the sample that counter selected does not appear on its output
    until GEN_LAT cycles later."""
    return [
        (start + p * pri + GEN_LAT, start + p * pri + width + GEN_LAT)
        for p in range(n_periods)
    ]


# Per-cycle generator control schedules. The generator's state -- two LFSRs, a
# phase accumulator and the NCO pipeline -- is CONTINUOUS across the whole run,
# so the model has to be driven through it in one call, exactly as the hardware
# is. (The old model could build each phase independently only because the
# generator was stateless apart from a PRI counter that wrapped cleanly at each
# boundary.)
#
# No pre-roll prefix. The generator is held in reset until RST_RELEASE and its
# registers -- LFSRs, phase accumulator, PRI counter, NCO output -- are all
# returned to their power-on values there, so the model's cycle 0 is the
# hardware's first out-of-reset cycle with phase 0's configuration ALREADY
# live. That is the payoff of resetting pulse_gen and of the staged bring-up:
# there is no default-configured window left to model at all.
_CD = _CTRL.defaults
pri_sched = []
width_sched = []
amp_sched = []
freq_sched = []
chirp_sched = []
noise_sched = []
phase_bounds = []  # (start, end) absolute sample-index range per phase
_pos = 0
for _ph in PHASES:
    _n = N_PERIODS * _ph.pri
    phase_bounds.append((_pos, _pos + _n))
    _pos += _n
    pri_sched.extend([_ph.pri] * _n)
    width_sched.extend([_ph.width] * _n)
    amp_sched.extend([_ph.amplitude] * _n)
    freq_sched.extend([_ph.freq] * _n)
    chirp_sched.extend([_ph.chirp_rate] * _n)
    noise_sched.extend([_ph.noise_amp] * _n)

TOTAL_SAMPLES = _pos
# Indexed by SAMPLE index, which is what every downstream model expects, and
# now identical to the model's own index: sample k is driven on hardware cycle
# PRE_ROLL + k.
raw = golden_pulse_gen(
    top.pulse_gen,
    TOTAL_SAMPLES,
    pri_sched,
    width_sched,
    amp_sched,
    freq_sched,
    chirp_sched,
    noise_sched,
)
assert len(raw) == TOTAL_SAMPLES

# dc_block's mean is one continuous IIR state across the WHOLE run (a single
# hardware instance, never reset between phases) -- so golden_dc_block must
# see the whole concatenated stimulus in one call, exactly like the hardware.
_mag_for_power = golden_magnitude(_DP.magnitude, raw)
power = golden_moving_avg(
    _DP.moving_avg, golden_dc_block(_DP.dc_block, _mag_for_power)
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
# 3b. Control frames -- one per phase, scheduled to land on its first sample.
# ---------------------------------------------------------------------------
def _phase_ctrl(ph):
    return pdw_ctrl_t(
        pulse_gen_pri=ph.pri,
        pulse_gen_width=ph.width,
        pulse_gen_freq=ph.freq,
        pulse_gen_chirp_rate=ph.chirp_rate,
        pulse_gen_amplitude=ph.amplitude,
        pulse_gen_noise_amp=ph.noise_amp,
        threshold_high=ph.thr_hi,
        threshold_low=ph.thr_lo,
        max_width=ph.max_width,
        min_width=ph.min_width,
        # Loopback on from phase 0 onward: the detector is fed pulse_gen's own
        # samples, not the garbage driven on rx0_s_axis_tdata.
        flags=CTRL_FLAG_LOOPBACK_EN,
    )


# {first-beat cycle: (phase index, frame bytes)}. type_to_bytes produces
# exactly what the hardware deserializer expects, by construction -- the two
# share their layout function (see stream/pypeline_stream_guide.md).
CTRL_FRAMES = {}
for _i, _ph in enumerate(PHASES):
    _start = _ctrl_frame_start(phase_bounds[_i][0])
    assert _start >= 0, (
        f"phase {_i}: control frame would start at cycle {_start}; PRE_ROLL "
        f"({PRE_ROLL}) is too small for {CTRL_BEATS} beats + latency {CTRL_LAT}"
    )
    assert _start not in CTRL_FRAMES, f"two control frames collide at cycle {_start}"
    CTRL_FRAMES[_start] = (_i, type_to_bytes(pdw_ctrl_t, _phase_ctrl(_ph)))

# The POISON frame: a well-formed write sent at cycle 0, entirely inside the
# control block's own reset, which must be decoded and then thrown away. Its
# values are chosen to be loud if they ever leaked -- thresholds low enough to
# declare a pulse immediately and an amplitude large enough to see -- so a
# failure shows up as detected pulses that the golden model never predicted,
# not as a subtle numeric drift.
POISON_CTRL = pdw_ctrl_t(
    pulse_gen_pri=7,
    pulse_gen_width=5,
    pulse_gen_freq=1 << 20,
    pulse_gen_chirp_rate=0,
    pulse_gen_amplitude=20000,
    pulse_gen_noise_amp=0,
    threshold_high=1,
    threshold_low=0,
    max_width=0xFFFFFFFF,
    min_width=0,
    flags=CTRL_FLAG_LOOPBACK_EN,
)
POISON_AT = 0
assert POISON_AT + CTRL_BEATS - 1 + CTRL_LAT < CTRL_RST_HOLD, (
    "pdw_tb: the poison frame must finish applying while tx0_s_axis_rst is "
    "still asserted, or it is not testing what it claims"
)
assert POISON_AT not in CTRL_FRAMES
CTRL_FRAMES[POISON_AT] = (-1, type_to_bytes(pdw_ctrl_t, POISON_CTRL))

# A final QUIESCE frame, landing exactly on sample TOTAL_SAMPLES. The last
# phase ends exactly on a pri boundary, so without this the generator's counter
# would wrap and start a further pulse the golden model never modelled -- while
# the engine's store-and-forward latency means this testbench is still draining
# then. (The old flat-port version did the same thing by dropping amplitude to
# 0 once `past_end`; framed control makes it an explicit write.)
_QUIESCE = _phase_ctrl(PHASES[-1])
_QUIESCE = _QUIESCE._replace(pulse_gen_amplitude=0, pulse_gen_noise_amp=0)
CTRL_QUIESCE_AT = _ctrl_frame_start(TOTAL_SAMPLES)
assert CTRL_QUIESCE_AT not in CTRL_FRAMES
CTRL_FRAMES[CTRL_QUIESCE_AT] = (len(PHASES), type_to_bytes(pdw_ctrl_t, _QUIESCE))
for _a, _b in zip(sorted(CTRL_FRAMES), sorted(CTRL_FRAMES)[1:]):
    assert _b - _a >= CTRL_BEATS, (
        f"control frames at cycles {_a} and {_b} overlap -- a phase is shorter "
        f"than one {CTRL_BEATS}-beat frame"
    )
# The cycle each frame's LAST beat is accepted, asserted against the real
# handshake during the run (see check_ctrl below). If control ever stalls or
# the deserializer's sizing changes, that assertion fires rather than every
# expectation downstream quietly shifting.
CTRL_LAST_BEAT = {s + CTRL_BEATS - 1: p for s, (p, _f) in CTRL_FRAMES.items()}

# What check_reset compares the live control registers against, and the cycle
# from which phase 0's write is guaranteed live.
_CTRL_FIELDS = tuple(pdw_ctrl_t._fields)
_DEFAULT_REGS = {f: int(getattr(_CTRL.defaults, f)) for f in _CTRL_FIELDS}
_PHASE0_REGS = {f: int(getattr(_phase_ctrl(PHASES[0]), f)) for f in _CTRL_FIELDS}
CTRL_REGS_SETTLED = CTRL_FRAME0_AT + CTRL_APPLY_OFFSET
assert CTRL_REGS_SETTLED <= RST_RELEASE


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


NOISE_K = _DP.noise_k
_NOISE_BITS = len(_DP.noise_t.typeof("val")) + NOISE_K + 1
# The noise estimator runs on the PRE-dc_block magnitude, which the hardware
# sees dc_block + moving_avg cycles EARLIER than the sample the hysteresis SM
# is classifying at the same moment. Mirror that skew rather than pairing them
# by index.
MAG_SKEW = _DP.dc_block.get_latency() + _DP.moving_avg.get_latency()


def _sext(v, bits):
    m = 1 << (bits - 1)
    return (v & ((1 << bits) - 1)) - ((v & m) << 1)


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
    # Combinational from the state as it stands on entry, like the hardware.
    out_in_idle = 1 if (st["state"] == "IDLE" and not above_high) else 0

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

    return out_pdw_valid, out_pdw_data, out_gate_valid, out_gate_last, out_in_idle


class _NoiseModel:
    """Mirror of the leaky noise-floor integrator in make_detect_pulses."""

    def __init__(self):
        self.acc = 0

    GUARD = _DP.noise_guard_shift
    SEED = _DP.noise_seed

    def step(self, mag_val, in_idle):
        est = self.acc >> NOISE_K
        looks_like_noise = mag_val <= ((est << self.GUARD) + self.SEED)
        if in_idle and looks_like_noise:
            self.acc = _sext(
                self.acc + (((mag_val << NOISE_K) - self.acc) >> NOISE_K),
                _NOISE_BITS,
            )
        return self.acc >> NOISE_K  # read post-update, as the hardware does


class _FreqAccumModel:
    """Untimed mirror of make_freq_accum's ping-pong block accumulators.

    Untimed is exact here: the hardware registers the conjugate product, and
    delays the accumulate-enable and the pulse-start reset by the SAME cycle,
    so the sequence of operations is identical and only its phase shifts. The
    values presented on the cycle after gate_last are the values this model
    holds after processing the gate_last beat.
    """

    K = _DP.freq_block_k
    BITS = len(_DP.freq_acc_t)

    def __init__(self):
        self.prev_i = 0
        self.prev_q = 0
        self.prev_valid = 0
        self._reset_accums()

    def _reset_accums(self):
        self.first_re = 0
        self.first_im = 0
        self.blk_re = 0
        self.blk_im = 0
        self.prv_re = 0
        self.prv_im = 0
        self.blk_cnt = 0
        self.beat_cnt = 0

    def step(self, cur_i, cur_q, beat_valid, beat_advance):
        d_re = cur_i * self.prev_i + cur_q * self.prev_q
        d_im = cur_q * self.prev_i - cur_i * self.prev_q
        pair_ok = beat_valid and self.prev_valid
        pulse_start = beat_valid and not self.prev_valid

        nb_re, nb_im, nb_cnt = self.blk_re, self.blk_im, self.blk_cnt
        nf_re, nf_im, nbeat = self.first_re, self.first_im, self.beat_cnt
        np_re, np_im = self.prv_re, self.prv_im
        if pair_ok:
            nb_re = _sext(nb_re + d_re, self.BITS)
            nb_im = _sext(nb_im + d_im, self.BITS)
            nb_cnt = self.blk_cnt + 1
            if self.beat_cnt < self.K:
                nf_re = _sext(nf_re + d_re, self.BITS)
                nf_im = _sext(nf_im + d_im, self.BITS)
                nbeat = self.beat_cnt + 1
            if nb_cnt == self.K:
                np_re, np_im = nb_re, nb_im
                nb_re, nb_im, nb_cnt = 0, 0, 0

        out = (
            nf_re,
            nf_im,
            _sext(np_re + nb_re, self.BITS),
            _sext(np_im + nb_im, self.BITS),
        )

        if pulse_start:
            self._reset_accums()
        else:
            self.first_re, self.first_im = nf_re, nf_im
            self.blk_re, self.blk_im, self.blk_cnt = nb_re, nb_im, nb_cnt
            self.prv_re, self.prv_im = np_re, np_im
            self.beat_cnt = nbeat

        if beat_advance:
            self.prev_i, self.prev_q, self.prev_valid = cur_i, cur_q, beat_valid
        return out


def _phase_of(sample_idx):
    for i, (s, e) in enumerate(phase_bounds):
        if s <= sample_idx < e:
            return i
    return len(PHASES) - 1


expected_pdws = []  # candidates: (phase_idx, toa, pulse_width, peak_power_u32)
expected_gate_packets = []  # every gate packet: (phase_idx, tuple_of_tdata_words)
# What the ENGINE should let through (README box 3): the accepted subset.
# (phase_idx, toa, width, peak, pkt_samples, status, pri, peak_db, noise_db,
#  freq_start, freq_stop)
expected_valid_pdws = []
expected_released = []  # (phase_idx, tuple_of_tdata_words)
expected_rejects = []  # (phase_idx, "glitch" | "cw") -- for non-vacuity only
first_gate_beat_sample_idx = None

_MEAS = top.pdw_engine.pdw_measure
_mag_seq = _mag_for_power
_fsm_st = _new_fsm_state()
_fa = _FreqAccumModel()
_nm = _NoiseModel()
_cur_packet = []
_prev_toa = 0
_have_prev = False
_gate_act = []  # per-sample gate_valid, for the control-frame quiet-window check
for _s in range(TOTAL_SAMPLES):
    pdw_valid, pdw_data, gate_valid, gate_last, in_idle = _fsm_step(
        _fsm_st, power[_s], thr_hi_sched[_s], thr_lo_sched[_s], max_width_sched[_s]
    )
    _gate_act.append(gate_valid)
    _mi = _s + MAG_SKEW
    noise_now = _nm.step(_mag_seq[_mi] if _mi < TOTAL_SAMPLES else 0, in_idle)
    # Path B: the delay line advances on gate_advance, which is the gate
    # register chain's structural twin and so first asserts GATE_LAT accepted
    # samples in. The sample it presents at index _s is raw[_s - GATE_LAT] --
    # the same relation the packet content check below rests on.
    _b_adv = 1 if _s >= GATE_LAT else 0
    _bi = _s - GATE_LAT
    _rri, _rrq = raw[_bi] if 0 <= _bi < TOTAL_SAMPLES else (0, 0)
    _fa_out = _fa.step(_rri, _rrq, gate_valid, _b_adv)
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
            # ADC-clip and DSP-overflow flags stay 0 for every packet here (no
            # amplitude reaches the int16 rail, and the FSM's overflow cannot
            # set with the engine always ready); their positive paths are
            # exercised in pdw_engine/pdw_engine_tb.py. The two measurement
            # flags below CAN legitimately set, so they are modelled rather
            # than asserted away.
            # The measurement, from the accumulations this same walk built.
            # `_fa_out` is what the hardware presents one cycle after
            # gate_last; `noise_now` and the candidate's peak/toa are what it
            # delays by freq_latency to meet it there.
            _m = golden_pdw_measure(
                _MEAS,
                _fa_out[0],
                _fa_out[1],
                _fa_out[2],
                _fa_out[3],
                noise_now,
                _peak,
                _toa,
                _prev_toa,
                _have_prev,
            )
            # PRI is measured between ACCEPTED pulses, so this advances here
            # and not at every candidate -- a rejected glitch must not corrupt
            # the interval reported for the next real pulse.
            _prev_toa, _have_prev = _toa, True
            _status = 0
            if _m["freq_degenerate"]:
                _status |= STATUS_FREQ_DEGENERATE
            if not _m["pri_valid"]:
                _status |= STATUS_PRI_INVALID
            expected_valid_pdws.append(
                (
                    _phase_of(_s),
                    _toa,
                    _width,
                    _peak & 0xFFFFFFFF,
                    len(_cur_packet),  # pkt_samples == beats pushed
                    _status,
                    _m["pri"],
                    _m["peak_power_db"],
                    _m["noise_power_db"],
                    _m["freq_start"],
                    _m["freq_stop"],
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

# Every control frame must be in flight over genuinely idle signal. The apply
# cycle is exact, so this is not needed for correctness -- it is here so that a
# future phase edit which shortens an idle gap fails with a clear message
# instead of reconfiguring the generator in the middle of a pulse.
for _i, _b in enumerate([b for b, _e in phase_bounds] + [TOTAL_SAMPLES]):
    if _b == 0:
        continue  # phase 0's frame lands during reset, before any sample
    _who = PHASES[_i].name if _i < len(PHASES) else "quiesce"
    _win = range(max(0, _b - CTRL_APPLY_OFFSET), _b)
    _busy = [s for s in _win if _gate_act[s]]
    assert not _busy, (
        f"control frame for {_who!r} occupies samples "
        f"{_win.start}..{_win.stop - 1}, but the previous phase still has gate "
        f"beats at {_busy} -- raise IDLE_MARGIN or that phase's pri"
    )

TOTAL_CYCLES = PRE_ROLL + TOTAL_SAMPLES
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
_pdw_sb = Scoreboard()  # rx2_m_axis_* -- Path A candidates, every detected pulse
_vpdw_sb = Scoreboard()  # rx1_m_axis_* -- engine PDW records, accepted only
_pkt_sb = Scoreboard()  # rx0_m_axis_* -- engine, released packets only


def _populate_scoreboards():
    for idx, (phase_idx, toa, width, peak) in enumerate(expected_pdws):
        _pdw_sb.expect((toa, width, peak), phase=phase_idx, idx=idx)
    for idx, exp in enumerate(expected_valid_pdws):
        phase_idx = exp[0]
        _vpdw_sb.expect(tuple(exp[1:]), phase=phase_idx, idx=idx)
    for idx, (phase_idx, pkt) in enumerate(expected_released):
        _pkt_sb.expect(pkt, phase=phase_idx, idx=idx)


# One sink per master port. Each enforces Xilinx-style tkeep compliance on
# every beat it accepts, which is what checks top.py's constant-keep sample
# ports as well as the serializers' real fill counts.
_CAND_T = top.candidate_rec_t
_VPDW_T = top.pdw_engine.valid_pdw_t
_ctrl_src = AxisSimSource(_CTRL.axis_intrf, AXIS_N)
_pkt_snk = AxisSimSink(top.axis32_intrf, AXIS_N)  # rx0_m -- released packets
_rep_snk = AxisSimSink(top.axis32_intrf, AXIS_N)  # tx1_m -- the replay leg
_vpdw_snk = AxisSimSink(top.pdw_tx.axis_intrf, AXIS_N)  # rx1_m -- PDW records
_cand_snk = AxisSimSink(top.cand_tx.axis_intrf, AXIS_N)  # rx2_m -- candidates

# gr_pdw_record.py parses the rx1_m_axis_* bytes directly on the host side, so
# its layout has to agree with the hardware's, not merely with itself.
VPDW_N_BYTES = byte_length(_VPDW_T)
CAND_N_BYTES = byte_length(_CAND_T)
assert _pystruct.calcsize(gr_pdw_record.RECORD_FORMAT) == VPDW_N_BYTES, (
    f"gr_pdw_record.RECORD_FORMAT is "
    f"{_pystruct.calcsize(gr_pdw_record.RECORD_FORMAT)} bytes but a PDW record "
    f"frame is {VPDW_N_BYTES} -- the host-side decoder and the hardware's "
    f"serializer have drifted apart"
)


def _words(frame):
    """A sample packet's frame bytes -> the tdata words it was sent as."""
    assert len(frame) % 4 == 0, f"sample packet frame is {len(frame)} bytes"
    return _pystruct.unpack(f"<{len(frame) // 4}I", frame)


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
    "first_beat_cycle": None,
    "alignment_checked": False,
    "n_pdw_done": 0,
    "n_vpdw_done": 0,
    "n_pkt_done": 0,
    "n_ctrl_frames": 0,
    "n_rst_cycles": 0,
    "phase0_live": False,
    "pdw_starts": [],
    "pkt_starts": [],
    "in_pdw_frame": False,
    "in_pkt_frame": False,
}

# Backpressure patterns on all four master ports. Store-and-forward is the
# whole point of box 3 -- a real-time gate stream feeding consumers that can
# stall -- so every consumer deliberately stalls, on mutually prime periods so
# the stalls drift against each other and against every phase's pri. The two
# released-packet legs stall on DIFFERENT periods, which is what exercises the
# broadcast interlock's ready AND rather than just passing one ready through.
#
# The golden model is unaffected: scoreboards compare content in arrival order,
# and backpressure only changes when frames arrive, never which. The one stream
# where that is not automatic is rx2_m (candidates), which has no path back
# into Path A and drops rather than stalls -- see CAND_READY_PERIOD below.
PKT_READY_PERIOD = 5
PDW_READY_PERIOD = 7
TX1_READY_PERIOD = 13
# Candidates are ~4 beats every pri (>= 192 cycles), so a 1-in-11 stall cannot
# make one frame still be draining when the next arrives -- no candidate is
# ever dropped here, which check_done asserts. The stall is real backpressure
# on a port a deployed system will tie high; the drop path itself is a
# negative control (hold this ready low for a whole phase), not a committed
# expectation.
CAND_READY_PERIOD = 11


@sim_input
def drive_stimulus():
    if ST["cycle"] == 0:
        _populate_scoreboards()
    n = ST["cycle"]

    # -- reset: two domains, staged ---------------------------------------
    # tx0_s_axis_rst drops first so the control block can be configured while
    # the datapath is still held; the other six drop at RST_HOLD. See top.py's
    # rst_main and the schedule derivation in section 0b.
    ctrl_rst_pin = 1 if n < CTRL_RST_HOLD else 0
    other_rst_pin = 1 if n < RST_HOLD else 0
    top.tx0_s_axis_rst = ctrl_rst_pin
    top.rx0_s_axis_rst = other_rst_pin
    top.rx0_m_axis_rst = other_rst_pin
    top.rx1_m_axis_rst = other_rst_pin
    top.rx2_m_axis_rst = other_rst_pin
    top.tx0_m_axis_rst = other_rst_pin
    top.tx1_m_axis_rst = other_rst_pin

    # -- control: one framed pdw_ctrl_t per phase -------------------------
    if n in CTRL_FRAMES:
        assert _ctrl_src.idle(), (
            f"cycle {n}: the previous control frame has not finished -- control "
            f"was back-pressured, which pdw_ctrl promises never happens"
        )
        _ctrl_src.send(CTRL_FRAMES[n][1])
    # Driving ready=1 rather than reading top.tx0_s_axis_tready: that output is
    # combinational, so reading it here (before convergence) would be a race.
    # check_ctrl asserts its real value is 1 on every cycle instead, which is
    # the same guarantee and a stronger check.
    _cf = _axis_flat(_ctrl_src.step(1))
    top.tx0_s_axis_tdata = _cf[0]
    top.tx0_s_axis_tkeep = _cf[1]
    top.tx0_s_axis_tlast = _cf[2]
    top.tx0_s_axis_tvalid = _cf[3]

    # -- samples ----------------------------------------------------------
    # Deliberately wrong data on the unselected mux leg: if the loopback flag
    # ever failed to select pulse_gen's own sample, this garbage would flow
    # through instead and fail the golden comparison loudly.
    top.rx0_s_axis_tdata = (0xDEAD0000 + (n & 0xFFFF)) & 0xFFFFFFFF
    top.rx0_s_axis_tkeep = (1 << AXIS_N) - 1
    top.rx0_s_axis_tlast = 0
    # Held low until the datapath leaves reset. The reset gate would drop these
    # beats anyway, so this is belt and braces -- but it keeps the stimulus
    # honest about what a host would really be doing.
    top.rx0_s_axis_tvalid = 0 if n < PRE_ROLL else 1

    # -- master-port backpressure -----------------------------------------
    top.rx0_m_axis_tready = 0 if (n % PKT_READY_PERIOD) == 0 else 1
    top.tx1_m_axis_tready = 0 if (n % TX1_READY_PERIOD) == 0 else 1
    top.rx1_m_axis_tready = 0 if (n % PDW_READY_PERIOD) == 0 else 1
    top.rx2_m_axis_tready = 0 if (n % CAND_READY_PERIOD) == 0 else 1
    top.tx0_m_axis_tready = 1  # ignored by design; driven for completeness
    ST["cycle"] = n + 1


@sim_output
def announce():
    if not ST["announced"]:
        ST["announced"] = True
        sim_print("=== pdw_tb: top-level PDW pipeline testbench ===")
        sim_print(
            f"  control: {len(CTRL_FRAMES)} frames of {CTRL_BEATS} beats, "
            f"apply latency {CTRL_LAT}, PRE_ROLL {PRE_ROLL} cycles; "
            f"records: PDW {VPDW_N_BYTES}B, candidate {CAND_N_BYTES}B"
        )
        for _i, _ph in enumerate(PHASES):
            sim_print(
                f"  phase {_i} ({_ph.name}): pri={_ph.pri} width={_ph.width} "
                f"amp={_ph.amplitude} thr_hi={_ph.thr_hi} thr_lo={_ph.thr_lo} "
                f"min_width={_ph.min_width} max_width={_ph.max_width} "
                f"-> {'RELEASED' if _ph.expect_valid and _ph.expect_pdws else 'none'}"
            )


@sim_output
def check_ctrl():
    """The control port's two structural promises, checked every cycle.

    Both are what makes the schedule above exact rather than approximate: if
    ready ever dropped, a frame would stretch and land late; if a frame's last
    beat landed anywhere but where CTRL_LAST_BEAT says, every expectation in
    this file would shift with it."""
    n = ST["cycle"] - 1  # drive_stimulus already advanced past this cycle
    assert int(top.tx0_s_axis_tready), (
        f"pdw_tb: tx0_s_axis_tready went low on cycle {n} -- pdw_ctrl promises "
        f"control is never back-pressured, and this testbench's frame timing "
        f"depends on it"
    )
    if int(top.tx0_s_axis_tvalid) and int(top.tx0_s_axis_tlast):
        assert n in CTRL_LAST_BEAT, (
            f"pdw_tb: a control frame ended on cycle {n}, which is not one of "
            f"the predicted cycles {sorted(CTRL_LAST_BEAT)}"
        )
        ST["n_ctrl_frames"] += 1


@sim_output
def check_reset():
    """Both halves of the staged bring-up, checked directly on the wire.

    NEGATIVE: the poison frame -- a well-formed write sent at cycle 0, wholly
    inside the control block's reset -- must be decoded and thrown away, and no
    master port may assert tvalid while the datapath is held.

    POSITIVE, and the more interesting one: phase 0's configuration must be
    LIVE by RST_RELEASE, i.e. the detector's very first sample is measured
    against real thresholds rather than CTRL_DEFAULTS. That is the whole reason
    pdw_ctrl sits in its own reset domain, and without this assertion the two
    domains could quietly collapse into one and only show up as a golden
    mismatch thousands of cycles later.
    """
    n = ST["cycle"] - 1
    if n > RST_RELEASE:
        return  # nothing here applies once the design is running
    regs = {f: int(getattr(top.ctrl_regs, f)) for f in _CTRL_FIELDS}
    if n < CTRL_REGS_SETTLED:
        assert regs == _DEFAULT_REGS, (
            f"pdw_tb: cycle {n}: control registers are not at their defaults "
            f"during reset -- the poison frame applied. Got {regs}"
        )
        ST["n_rst_cycles"] += 1
    if n == RST_RELEASE:
        assert regs == _PHASE0_REGS, (
            f"pdw_tb: cycle {n} is the datapath's first out-of-reset cycle but "
            f"phase 0's configuration is not live yet -- the staged bring-up is "
            f"broken (is pdw_ctrl on global_rst instead of ctrl_rst?). "
            f"Got {regs}"
        )
        ST["phase0_live"] = True
    if n < RST_RELEASE:
        # Read each port by name, NOT via getattr(top, <string>): the sim
        # framework decides which @sim_output functions to invoke from the
        # top.<port> references it can see statically in the body, so a
        # dynamic lookup makes the whole function look like it touches no
        # ports at all -- and it is then never called. That failure is silent:
        # every assertion here simply never runs.
        live = (
            int(top.tx0_m_axis_tvalid)
            | int(top.rx0_m_axis_tvalid)
            | int(top.tx1_m_axis_tvalid)
            | int(top.rx1_m_axis_tvalid)
            | int(top.rx2_m_axis_tvalid)
        )
        assert not live, (
            f"pdw_tb: cycle {n}: a master port asserted tvalid while the "
            f"design is in reset -- AXI forbids it, and a host must not see "
            f"the previous session's data on a channel it has just opened "
            f"(tx0_m={int(top.tx0_m_axis_tvalid)} "
            f"rx0_m={int(top.rx0_m_axis_tvalid)} "
            f"tx1_m={int(top.tx1_m_axis_tvalid)} "
            f"rx1_m={int(top.rx1_m_axis_tvalid)} "
            f"rx2_m={int(top.rx2_m_axis_tvalid)})"
        )


@sim_output
def check_pdw():
    """rx2_m_axis_*: Path A's candidate records, one 16-byte frame per detected
    pulse whether the engine accepts it or not."""
    # Only build the interface word on a real transfer. AxisSimSink.step()
    # returns immediately for an invalid beat, so skipping the call is exactly
    # equivalent -- and it matters: assembling one costs a nested struct
    # construction, and doing that on all four ports every cycle for the whole
    # run dominated this testbench's wall time.
    transferred = int(top.rx2_m_axis_tvalid) and int(top.rx2_m_axis_tready)
    if transferred:
        _cand_snk.step(
            _axis_word(
                top.cand_tx.axis_intrf,
                int(top.rx2_m_axis_tdata),
                int(top.rx2_m_axis_tkeep),
                int(top.rx2_m_axis_tlast),
                1,
            )
        )
    frame = _cand_snk.recv_nowait()
    if frame is None:
        return
    assert len(frame) == CAND_N_BYTES, (
        f"pdw_tb: candidate frame is {len(frame)} bytes, expected {CAND_N_BYTES}"
    )
    rec = type_from_bytes(_CAND_T, frame)
    got = (int(rec.toa), int(rec.pulse_width), int(rec.peak_power))
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
    """rx1_m_axis_*: README box 3's metadata output, only ACCEPTED pulses, one
    40-byte frame each. Each must START before its own released packet -- the
    ordering a DMA consumer needs to size the transfer that follows -- which is
    checked against pkt_starts in check_done.

    The frame bytes are also handed to gr_pdw_record.unpack_records() and the
    result compared field for field, so the host-side decoder is tested against
    real hardware bytes rather than only against a synthetic record."""
    transferred = int(top.rx1_m_axis_tvalid) and int(top.rx1_m_axis_tready)
    if transferred and not ST["in_pdw_frame"]:
        ST["in_pdw_frame"] = True
        ST["pdw_starts"].append(ST["cycle"] - 1)
    if transferred:  # see the note in check_pdw on why this is gated
        _vpdw_snk.step(
            _axis_word(
                top.pdw_tx.axis_intrf,
                int(top.rx1_m_axis_tdata),
                int(top.rx1_m_axis_tkeep),
                int(top.rx1_m_axis_tlast),
                1,
            )
        )
    if transferred and int(top.rx1_m_axis_tlast):
        ST["in_pdw_frame"] = False
    frame = _vpdw_snk.recv_nowait()
    if frame is None:
        return
    assert len(frame) == VPDW_N_BYTES, (
        f"pdw_tb: PDW frame is {len(frame)} bytes, expected {VPDW_N_BYTES}"
    )
    rec = type_from_bytes(_VPDW_T, frame)
    got = (
        int(rec.toa),
        int(rec.pulse_width),
        int(rec.peak_power),
        int(rec.pkt_samples),
        int(rec.status_flags),
        int(rec.pri),
        int(rec.peak_power_db),
        int(rec.noise_power_db),
        int(rec.freq_start),
        int(rec.freq_stop),
    )
    # The same bytes through the host-side reader must give the same numbers.
    host = gr_pdw_record.unpack_records(frame)
    assert len(host) == 1, f"pdw_tb: unpack_records returned {len(host)} records"
    for _f in ("toa", "pulse_width", "peak_power", "pkt_samples", "status_flags",
               "pri", "peak_power_db", "noise_power_db", "freq_start", "freq_stop"):
        assert host[0][_f] == int(getattr(rec, _f)), (
            f"pdw_tb: gr_pdw_record decoded {_f}={host[0][_f]} but the frame "
            f"holds {int(getattr(rec, _f))} -- RECORD_FORMAT no longer matches "
            f"valid_pdw_t's field order"
        )
    assert not (got[4] & STATUS_PKT_FIFO_FULL), (
        "pdw_tb: this PDW's packet lost beats to a full store-and-forward FIFO "
        "-- packet contents are corrupted; increase pdw_engine's depth"
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
            f"expected (toa,width,peak,pkt_samples,status,pri,peak_db,"
            f"noise_db,freq_start,freq_stop)={exp}, got {got_v}"
        )
        raise AssertionError(
            f"pdw_tb: valid_pdw {idx} (phase {phase}): expected {exp}, got {got_v}"
        )
    # Ordering is checked on FRAME STARTS, not completions: the PDW record is
    # now a ten-beat frame streaming out of a serializer, so while the engine
    # still hands it over before it starts sending the packet, the record's
    # last beat can legitimately land after the packet's first ones.
    assert len(ST["pdw_starts"]) > ST["n_pkt_done"], (
        f"pdw_tb: valid_pdw {idx} arrived out of order -- "
        f"{len(ST['pdw_starts'])} PDW frames started vs {ST['n_pkt_done']} "
        f"packets already done; each PDW must begin before its own packet"
    )
    sim_print(
        f"pdw_tb: valid_pdw {idx} (phase {phase}) OK: toa={got[0]} width={got[1]} "
        f"peak={got[2]} pkt_samples={got[3]} status=0x{got[4]:08x} pri={got[5]} "
        f"peak={got[6] / 256.0:.2f}dB noise={got[7] / 256.0:.2f}dB "
        f"f0={got[8] / 65536.0:+.5f} f1={got[9] / 65536.0:+.5f} turns/sample"
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
        if not ST["in_pkt_frame"]:
            ST["in_pkt_frame"] = True
            ST["pkt_starts"].append(ST["cycle"] - 1)
    if int(top.rx0_m_axis_tlast) and not int(top.rx0_m_axis_tvalid):
        raise AssertionError("pdw_tb: rx0_m_axis_tlast asserted without tvalid -- illegal AXIS")
    if transferred:  # see the note in check_pdw on why this is gated
        _pkt_snk.step(
            _axis_word(
                top.axis32_intrf,
                int(top.rx0_m_axis_tdata),
                int(top.rx0_m_axis_tkeep),
                int(top.rx0_m_axis_tlast),
                1,
            )
        )
    # The replay leg gets the same beat from the broadcast interlock, so it must
    # produce a byte-identical frame. This is the only check of the fanout: leg
    # 1 could be mis-wired to a stale register or to leg 0's ready and
    # everything else here would still pass.
    if int(top.tx1_m_axis_tvalid) and int(top.tx1_m_axis_tready):
        _rep_snk.step(
            _axis_word(
                top.axis32_intrf,
                int(top.tx1_m_axis_tdata),
                int(top.tx1_m_axis_tkeep),
                int(top.tx1_m_axis_tlast),
                1,
            )
        )
    if transferred and int(top.rx0_m_axis_tlast):
        ST["in_pkt_frame"] = False
    frame = _pkt_snk.recv_nowait()
    if frame is None:
        return
    replay = _rep_snk.recv_nowait()
    assert replay is not None, (
        "pdw_tb: rx0_m_axis_* completed a packet with no matching frame on the "
        "replay leg tx1_m_axis_* -- the broadcast interlock let the two legs "
        "diverge"
    )
    assert replay == frame, (
        f"pdw_tb: the replay leg's packet differs from the capture leg's "
        f"({len(replay)} vs {len(frame)} bytes)"
    )
    got_pkt = _words(frame)
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
        earliest = PRE_ROLL + first_gate_beat_sample_idx + DSP_LAT
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
        # rx2_m_axis_* drops rather than stalls (Path A cannot be stopped), so
        # "every candidate arrived" is a real result here, not a given -- and
        # it is what lets check_pdw compare exactly instead of tolerating gaps.
        assert ST["n_pdw_done"] == len(expected_pdws), (
            f"pdw_tb: received {ST['n_pdw_done']} candidate records, expected "
            f"{len(expected_pdws)} -- rx2_m_axis_* dropped {len(expected_pdws) - ST['n_pdw_done']} "
            f"(CAND_READY_PERIOD={CAND_READY_PERIOD} is stalling it too hard for "
            f"a {CAND_N_BYTES // 4}-beat frame to drain between pulses)"
        )
        assert ST["n_ctrl_frames"] == len(CTRL_FRAMES), (
            f"pdw_tb: {ST['n_ctrl_frames']} control frames were accepted, sent "
            f"{len(CTRL_FRAMES)}"
        )
        # check_reset only asserts inside a window, so prove that window was
        # actually visited rather than skipped -- otherwise a scheduling
        # mistake would silently turn the reset test into nothing at all.
        assert ST["n_rst_cycles"] == CTRL_REGS_SETTLED, (
            f"pdw_tb: check_reset saw {ST['n_rst_cycles']} in-reset cycles, "
            f"expected {CTRL_REGS_SETTLED} -- the reset window was not driven"
        )
        assert ST["phase0_live"], (
            "pdw_tb: check_reset never reached RST_RELEASE, so the "
            "configure-before-release path went unverified"
        )
        # Record k must belong to packet k, not be deferred into the next
        # pulse's slot: its frame has to start before packet k+1 does.
        #
        # NOT "before packet k does". The engine still hands the record over in
        # EMIT_PDW before entering SEND_PKT, but the record now goes through a
        # serializer whose first beat costs a fill cycle the packet path does
        # not pay -- measured, the record's first beat lands one cycle AFTER
        # its packet's. The two streams then run concurrently on separate
        # ports. See the README's note on this.
        for _k in range(ST["n_pkt_done"] - 1):
            assert ST["pdw_starts"][_k] < ST["pkt_starts"][_k + 1], (
                f"pdw_tb: PDW record {_k} started at cycle "
                f"{ST['pdw_starts'][_k]}, not before the NEXT pulse's packet at "
                f"{ST['pkt_starts'][_k + 1]} -- a record has slipped out of its "
                f"own pulse's slot"
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
    check_ctrl()
    check_reset()
    check_pdw()
    check_valid_pdw()
    check_packet()
    check_done()
