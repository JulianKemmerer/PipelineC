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
STAGE A vs STAGE B (see README.md section 5 and pulse_detect.py's own
"gate_ready / backpressure" TODO for the underlying issue)
-----------------------------------------------------------------------------
Path B's delay line (`make_delay_line` in pulse_detect/pulse_detect.py)
currently pushes AND drains every cycle, so it only shows the FIFO's
incidental 2-cycle push-to-valid latency -- not a delay that tracks the DSP
math pipeline's real latency. `PATH_B_SKEW` below is the single knob that
encodes which alignment the golden model expects:

  Stage A (what this file currently ships as): PATH_B_SKEW reproduces TODAY'S
  hardware exactly (computed from measured latencies, not hardcoded), so this
  testbench passes and proves the harness itself -- golden model, drivers,
  scoreboards -- is correct.

  Stage B (the next step, NOT done in this commit): flip PATH_B_SKEW to 0 --
  the CORRECT alignment, where the packet carries exactly the raw samples
  that produced its own gate beats -- and this testbench is expected to FAIL
  until pulse_detect.py's delay line is fixed to match (see that function's
  docstring for the fix). At that point this testbench becomes the
  hardware's acceptance test.

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
FIFO_LAT = _DP.delay_line_latency  # FWFT FIFO's inherent push-to-valid latency

# Stage A: today's hardware delays the raw sample by FIFO_LAT cycles from the
# same real testbench cycle that the FSM's *input* (avg_o, DSP_LAT cycles
# behind raw) is being consumed -- so the raw sample visible on that same
# cycle is DSP_LAT - FIFO_LAT samples newer than the one the FSM is now
# looking at. See README.md section 5 for the full derivation.
# Stage A: PATH_B_SKEW = DSP_LAT - FIFO_LAT  (reproduces today's hardware)
#
# STAGE B (shipped as of this line): the CORRECT alignment -- the packet
# must carry exactly the raw samples that produced its own gate beats. This
# is now expected to FAIL until pulse_detect.py's delay line is fixed to
# match (see the module docstring and README.md section 5); at that point
# this testbench is the fix's acceptance test.
PATH_B_SKEW = 0


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
    auto_threshold: bool = True  # False for phases 3/4, which set thr_hi/thr_lo below
    thr_hi: int = 0
    thr_lo: int = 0
    expect_pdws: bool = True  # False for phases 3/4: must be fully filtered out


PHASES = [
    Phase(name="baseline", pri=256, width=64, amplitude=600),
    Phase(name="short pulse (moving_avg edge smear)", pri=192, width=16, amplitude=800),
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
    ),
    Phase(
        name="signal too weak",
        pri=256,
        width=64,
        amplitude=40,
        auto_threshold=False,  # filled in below from phase 0's calibrated values
        expect_pdws=False,
    ),
    Phase(name="CW / max_width cap", pri=512, width=300, amplitude=600, max_width=64),
]

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

# Phase 4 (signal too weak): reuse phase 0's calibrated thresholds -- the
# whole point is that phase 4's much smaller amplitude must fail to cross
# phase 0's threshold_high.
PHASES[4].thr_hi = PHASES[0].thr_hi
PHASES[4].thr_lo = PHASES[0].thr_lo

assert SUPPRESS_THRESHOLD < 2**32, "SUPPRESS_THRESHOLD must fit the uint32_t threshold_high port"
for _i, _ph in enumerate(PHASES):
    if _i == 3:
        _start, _end = phase_bounds[3]
        _windows = _nominal_windows(_start, _ph.pri, _ph.width, N_PERIODS)
        _own_peak = max(max(power[s:e]) for s, e in _windows)
        assert SUPPRESS_THRESHOLD > _own_peak, (
            f"SUPPRESS_THRESHOLD ({SUPPRESS_THRESHOLD}) must exceed phase 3's own "
            f"peak power ({_own_peak}) to guarantee suppression"
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
for _ph in PHASES:
    thr_hi_sched.extend([_ph.thr_hi] * (N_PERIODS * _ph.pri))
    thr_lo_sched.extend([_ph.thr_lo] * (N_PERIODS * _ph.pri))
    max_width_sched.extend([_ph.max_width] * (N_PERIODS * _ph.pri))
assert len(thr_hi_sched) == TOTAL_SAMPLES


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
    }


def _fsm_step(st, p, thr_hi, thr_lo, max_width):
    """One simulated hardware cycle. Registers are read here as committed
    from the PREVIOUS call (matching hardware's read-before-write Reg
    semantics), and this call's writes become visible on the NEXT call --
    so the returned (pdw_valid, pdw_data, gate_valid, gate_last) values are
    exactly what pulse_detect_fsm's output ports show this cycle."""
    out_pdw_valid, out_pdw_data = st["pdw_valid"], st["pdw_data"]
    out_gate_valid, out_gate_last = st["gate_valid_r"], st["gate_last_r"]

    if st["pdw_valid"]:  # drain (candidate_pdw_ready == 1 always in this tb)
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

    if st["state"] == "IDLE":
        if above_high:
            st["state"] = "PULSE"
            st["width"] = 1
            st["peak"] = p
    elif st["state"] == "PULSE":
        if below_low:
            st["pdw_data"] = (st["width"], st["peak"])
            st["pdw_valid"] = 1
            st["state"] = "IDLE"
        else:
            new_width = st["width"] + 1
            new_peak = p if p > st["peak"] else st["peak"]
            if new_width >= max_width:
                st["pdw_data"] = (new_width, new_peak)
                st["pdw_valid"] = 1
                st["state"] = "RECOVER"
            else:
                st["width"] = new_width
                st["peak"] = new_peak
    else:  # RECOVER
        if below_low:
            st["state"] = "IDLE"

    return out_pdw_valid, out_pdw_data, out_gate_valid, out_gate_last


def _phase_of(sample_idx):
    for i, (s, e) in enumerate(phase_bounds):
        if s <= sample_idx < e:
            return i
    return len(PHASES) - 1


expected_pdws = []  # ordered list of (phase_idx, pulse_width, peak_power_u32)
expected_packets = []  # ordered list of (phase_idx, tuple_of_tdata_words)
first_gate_beat_sample_idx = None

_fsm_st = _new_fsm_state()
_cur_packet = []
for _s in range(TOTAL_SAMPLES):
    pdw_valid, pdw_data, gate_valid, gate_last = _fsm_step(
        _fsm_st, power[_s], thr_hi_sched[_s], thr_lo_sched[_s], max_width_sched[_s]
    )
    if pdw_valid:
        width, peak = pdw_data
        expected_pdws.append((_phase_of(_s), width, peak & 0xFFFFFFFF))
        assert peak < 2**32, (
            f"golden peak_power {peak} exceeds the uint32_t candidate_pdw_peak_power "
            f"port's range -- reduce a phase's amplitude"
        )
    if gate_valid:
        if first_gate_beat_sample_idx is None:
            first_gate_beat_sample_idx = _s
        raw_idx = _s + PATH_B_SKEW
        i_val, q_val = raw[raw_idx] if 0 <= raw_idx < TOTAL_SAMPLES else (0, 0)
        tdata = ((q_val & 0xFFFF) << 16) | (i_val & 0xFFFF)
        _cur_packet.append(tdata)
    if gate_last:
        expected_packets.append((_phase_of(_s), tuple(_cur_packet)))
        _cur_packet = []

assert first_gate_beat_sample_idx is not None, "golden model produced no gate beats at all"

# ---------------------------------------------------------------------------
# 5. Non-vacuity assertions (build-time, plain Python) -- a config edit that
#    quietly guts the test should fail loudly here, not pass silently.
# ---------------------------------------------------------------------------
for _i, _ph in enumerate(PHASES):
    _n = sum(1 for p, *_ in expected_pdws if p == _i)
    if _ph.expect_pdws:
        assert _n == N_PERIODS, f"phase {_i} ({_ph.name!r}): expected {N_PERIODS} PDWs, golden model produced {_n}"
    else:
        assert _n == 0, f"phase {_i} ({_ph.name!r}): expected 0 PDWs, golden model produced {_n}"

_cw_pdws = [w for p, w, _ in expected_pdws if p == 5]
assert all(w == PHASES[5].max_width for w in _cw_pdws), (
    f"phase 5 (CW cap): expected every pulse_width == {PHASES[5].max_width}, got {_cw_pdws}"
)

assert len(expected_packets) == len(expected_pdws), (
    f"expected_packets ({len(expected_packets)}) and expected_pdws "
    f"({len(expected_pdws)}) must be produced 1:1 by the same FSM walk"
)
for _idx, (_phase_idx, _pkt) in enumerate(expected_packets):
    _width = expected_pdws[_idx][1]
    assert len(_pkt) == _width and len(_pkt) > 0, (
        f"packet {_idx} (phase {_phase_idx}): length {len(_pkt)} != pulse_width {_width}"
    )

TOTAL_CYCLES = TOTAL_SAMPLES
sim_print(
    f"pdw_tb: {len(PHASES)} phases, {TOTAL_SAMPLES} stimulus samples, "
    f"{len(expected_pdws)} expected PDWs/packets, PATH_B_SKEW={PATH_B_SKEW}, "
    f"DSP_LAT={DSP_LAT} GATE_LAT={GATE_LAT} FIFO_LAT={FIFO_LAT}"
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
_pdw_sb = Scoreboard()
_pkt_sb = Scoreboard()


def _populate_scoreboards():
    for idx, (phase_idx, width, peak) in enumerate(expected_pdws):
        _pdw_sb.expect((width, peak), phase=phase_idx, idx=idx)
    for idx, (phase_idx, pkt) in enumerate(expected_packets):
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
    "n_pkt_done": 0,
}


@sim_input
def drive_stimulus():
    if ST["cycle"] == 0:
        _populate_scoreboards()
    n = ST["cycle"]
    idx = n if n < TOTAL_SAMPLES else TOTAL_SAMPLES - 1
    top.pulse_gen_pri = PHASES[_phase_of(idx)].pri
    top.pulse_gen_width = PHASES[_phase_of(idx)].width
    top.pulse_gen_amplitude = PHASES[_phase_of(idx)].amplitude
    top.threshold_high = thr_hi_sched[idx]
    top.threshold_low = thr_lo_sched[idx]
    top.max_width = max_width_sched[idx]
    top.pulse_loopback_en = 1
    top.candidate_pdw_ready = 1
    top.rx0_m_axis_tready = 1
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
                f"max_width={_ph.max_width}"
            )


@sim_output
def check_pdw():
    if not int(top.candidate_pdw_valid):
        return
    got = (int(top.candidate_pdw_pulse_width), int(top.candidate_pdw_peak_power))
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
            f"expected width={exp[0]} peak={exp[1]}, got width={got_v[0]} peak={got_v[1]}"
        )
        raise AssertionError(
            f"pdw_tb: candidate {idx} (phase {phase}): expected {exp}, got {got_v}"
        )
    sim_print(f"pdw_tb: candidate {idx} (phase {phase}) OK: width={got[0]} peak={got[1]}")
    ST["n_pdw_done"] += 1


@sim_output
def check_packet():
    if int(top.rx0_m_axis_tvalid):
        if ST["first_beat_cycle"] is None:
            # ST["cycle"] has already been advanced past this cycle by
            # drive_stimulus() (which runs before this checker within the
            # same clock cycle), so the cycle this beat landed on is
            # ST["cycle"] - 1.
            ST["first_beat_cycle"] = ST["cycle"] - 1
        ST["cur_packet"].append(int(top.rx0_m_axis_tdata))
    if not int(top.rx0_m_axis_tlast):
        return
    if not int(top.rx0_m_axis_tvalid):
        raise AssertionError("pdw_tb: rx0_m_axis_tlast asserted without tvalid -- illegal AXIS")
    got_pkt = tuple(ST["cur_packet"])
    ST["cur_packet"] = []
    result = _pkt_sb.check(got_pkt)
    idx = result.get("idx", "?")
    phase = result.get("phase", "?")

    if not ST["alignment_checked"]:
        # Alignment self-check: the first gate beat's real testbench cycle
        # should be exactly first_gate_beat_sample_idx + DSP_LAT (see the
        # module docstring's derivation) -- fires a clear message rather than
        # an opaque data mismatch if a latency assumption above is wrong.
        ST["alignment_checked"] = True
        expected_first_cycle = first_gate_beat_sample_idx + DSP_LAT
        actual_cycle = ST["first_beat_cycle"]
        assert actual_cycle == expected_first_cycle, (
            f"pdw_tb: alignment self-check failed: first gate beat expected at "
            f"cycle {expected_first_cycle} (sample {first_gate_beat_sample_idx} + "
            f"DSP_LAT {DSP_LAT}), landed at cycle {actual_cycle} instead -- a "
            f"latency assumption (DSP_LAT/GATE_LAT/FIFO_LAT) is wrong"
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
    deadline = TOTAL_CYCLES + DSP_LAT + GATE_LAT + 256
    if ST["cycle"] >= TOTAL_CYCLES and _pdw_sb.pending() == 0 and _pkt_sb.pending() == 0:
        sim_print(
            f"pdw_tb: all {len(expected_pdws)} PDWs and {len(expected_packets)} "
            f"packets matched -- Test DONE!"
        )
        sim_finish()
    assert ST["cycle"] < deadline, (
        f"pdw_tb: not done after {ST['cycle']} cycles "
        f"({ST['n_pdw_done']}/{len(expected_pdws)} PDWs, "
        f"{ST['n_pkt_done']}/{len(expected_packets)} packets)"
    )


@MAIN(125.0)
def pdw_tb_main():
    drive_stimulus()
    announce()
    check_pdw()
    check_packet()
    check_done()
