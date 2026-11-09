# pyright: reportInvalidTypeForm=none
"""Reset semantics for the PDW blocks: a reset mid-activity leaves each block
exactly as at power-on.

top.py resets its MAINs with `reset_registers="all"`: every register below
them -- this project's own, the library FIFOs, joins, serializers and ROM
pipelines, the DSP filters' history and every pipeline stage -- returns to
its initial value in the cycle after the reset is asserted. This testbench
checks that for the three blocks whose reset matters most, each run in two
copies, under two resets from `rst_gen`:

- `dut_a` is reset in cycle RESET_AT, in the middle of everything below;
- `dut_b` is held in reset from cycle 0 to RESET_AT.

After RESET_AT the two must agree in every cycle -- the reset leaves no trace
-- and the checker (not reset) asserts that, plus what the restarted copy must
produce:

- the pulse_detect -> pulse_extract chain, wired as top.py's pdw_main, with
  each copy's own two-pulse stimulus. RESET_AT lands INSIDE pulse 1: a packet
  is part written, its descriptor not pushed, the hysteresis SM in PULSE and
  Path B's delay line holding samples. After the reset both copies emit
  exactly pulse 1 and pulse 2 of their restarted stimulus; pulse 1 reports
  PRI invalid with a TOA counted from release (pulse_measure's PRI state
  resets with pulse_detect's toa_counter), and each packet carries its
  PDW's pkt_samples beats. Glitch rejection is off (MIN_WIDTH = 1), so a
  release artifact -- filter history carried across the reset -- would show
  as an extra PDW in dut_a only.
- pdw_ctrl: a POISON frame applies in dut_a before the reset (dut_b, in
  reset, never decodes it), then a frame abandoned three beats in at the
  reset. After the reset both read CTRL_DEFAULTS until CFG_B, sent from each
  copy's restarted counter, applies -- no prefix of the abandoned frame joins
  it.
- the internal-error alarm: one in flight at the reset is abandoned; one
  after it destroys exactly DROPS samples.

Run (native, then the same against GHDL):
    pypelinec examples/pypeline/dsp/pdw/pdw_reset_test.py --sim --comb --run all
    python3 src/pypeline_sim_debug.py examples/pypeline/dsp/pdw/pdw_reset_test.py \\
        --sim --comb --run all
"""

import pdw_paths  # noqa: F401  (puts include/pypeline on sys.path)

from pypeline import (
    MAIN,
    NamedTuple,
    Reg,
    Wire,
    hw_func,
    int16_t,
    make_clock,
    make_reset,
    sim_assert,
    sim_finish,
    sim_print,
    struct,
    type_to_bytes,
    uint1_t,
    uint4_t,
    uint8_t,
    uint16_t,
    uint32_t,
    uint_to_array_le,
)

from dsp.dsp_tb import golden_dc_block, golden_magnitude, golden_moving_avg
from pdw_alarm import make_error_alarm
from pdw_ctrl import CTRL_DEFAULTS, make_pdw_ctrl, pdw_ctrl_t
from pulse_detect import make_pulse_detect
from pulse_extract import STATUS_PRI_INVALID, make_pulse_extract

# Small FIFOs: this test's packets are tens of beats.
_DP = make_pulse_detect()
_ENG = make_pulse_extract(_DP, depth=512, n_pkts=8)
ctrl = make_pdw_ctrl(4)
DROPS = 8
alarm = make_error_alarm(drop_samples=DROPS, max_cycles=200)

AMPLITUDE = 12000
PULSE_W = 40
IDLE = 120  # >= the DSP chain's fill plus room for the noise estimator
P1_AT = IDLE  # in each copy's own sample count
P2_AT = IDLE * 2 + PULSE_W
RESET_AT = P1_AT + PULSE_W // 2  # mid-pulse: packet part written, no descriptor
MIN_WIDTH = 1  # no glitch rejection: a release artifact would be a PDW
N_CYCLES = RESET_AT + P2_AT + PULSE_W + 260
# The stimulus's 4-sample rotation starts on a multiple of 4 in each pulse
assert P1_AT % 4 == 0 and P2_AT % 4 == 0


def _stimulus(pulses):
    """(i, q) per sample, as pulse_sample() makes it: Q a quarter period out
    of phase with I, so the phasor is not degenerate."""
    n = max(s + w for s, w in pulses) + IDLE
    out = [(0, 0)] * n
    rot = [(AMPLITUDE, 0), (0, AMPLITUDE), (-AMPLITUDE, 0), (0, -AMPLITUDE)]
    for start, width in pulses:
        for k in range(width):
            out[start + k] = rot[(start + k) % 4]
    return out


def _thresholds(raw):
    """Thresholds from the real conditioned power, so this test does not
    depend on dc_block/moving_avg's internal scaling staying put."""
    power = golden_moving_avg(
        _DP.moving_avg,
        golden_dc_block(_DP.dc_block, golden_magnitude(_DP.magnitude, raw)),
    )
    peak = max(power)
    assert peak > 0, "stimulus produced no power at all"
    return peak // 2, peak // 4


THR_HI, THR_LO = _thresholds(_stimulus([(P1_AT, PULSE_W), (P2_AT, PULSE_W)]))

# Control frames, as ten 32-bit beats (tdata byte j = struct byte 4*beat + j)
POISON = pdw_ctrl_t(
    pulse_gen_pri=77,
    pulse_gen_width=5,
    pulse_gen_freq=123,
    pulse_gen_chirp_rate=4,
    pulse_gen_amplitude=999,
    pulse_gen_noise_amp=3,
    threshold_high=0x1234,
    threshold_low=0x123,
    max_width=500,
    min_width=7,
    flags=1,
)
CFG_B = pdw_ctrl_t(
    pulse_gen_pri=1000,
    pulse_gen_width=40,
    pulse_gen_freq=1 << 28,
    pulse_gen_chirp_rate=0,
    pulse_gen_amplitude=8000,
    pulse_gen_noise_amp=0,
    threshold_high=0xABCDE,
    threshold_low=0x5555,
    max_width=4000,
    min_width=2,
    flags=0,
)


def _words(cfg):
    b = type_to_bytes(pdw_ctrl_t, cfg)
    return tuple(int.from_bytes(b[i : i + 4], "little") for i in range(0, len(b), 4))


POISON_W = _words(POISON)
CFG_B_W = _words(CFG_B)
N_BEATS = len(POISON_W)
POISON_AT = 2  # global cycle; both copies see it, dut_b is in reset
PARTIAL_AT = RESET_AT - 3  # three beats of a frame the reset abandons
CFG_B_AT = 5  # in each copy's own count after the reset
CFG_B_APPLIED = RESET_AT + 1 + CFG_B_AT + N_BEATS - 1 + ctrl.latency
ALARM_PRE_AT = RESET_AT - 4  # global cycle: in flight at the reset
ALARM_POST_AT = 40  # in each copy's own count after the reset
assert POISON_AT + N_BEATS + ctrl.latency < PARTIAL_AT
assert ALARM_PRE_AT + DROPS > RESET_AT

pdw_stream_t = _ENG.pdw_out_intrf.stream_t
pkt_stream_t = _ENG.pkt_out_intrf.stream_t


@struct
class tb_out_t(NamedTuple):
    pdw: pdw_stream_t
    pkt: pkt_stream_t
    regs: pdw_ctrl_t
    ctrl_ready: uint1_t
    alarm: alarm.return_t


@hw_func
def pulse_sample(n: uint16_t) -> _DP.complex_t:
    in1: uint1_t = (n >= P1_AT) & (n < P1_AT + PULSE_W)
    in2: uint1_t = (n >= P2_AT) & (n < P2_AT + PULSE_W)
    sel: uint16_t = n & 3
    amp: int16_t = AMPLITUDE
    namp: int16_t = -AMPLITUDE
    i: int16_t = 0
    q: int16_t = 0
    if in1 | in2:
        if sel == 0:
            i = amp
        elif sel == 1:
            q = amp
        elif sel == 2:
            i = namp
        else:
            q = namp
    return _DP.complex_t(i=_DP.rail_t(val=i), q=_DP.rail_t(val=q))


@hw_func
def frame_beat(words: uint32_t[N_BEATS], idx: uint16_t) -> uint32_t:
    i4: uint4_t = idx
    return words[i4]


@hw_func
def pdw_blocks(rst: uint1_t, t: uint16_t) -> tb_out_t:
    n: Reg[uint16_t]  # this copy's samples
    m: Reg[uint16_t]  # this copy's cycles
    o: tb_out_t

    # -- pulse_detect -> pulse_extract, as top.py's pdw_main wires them ----
    max_w: uint32_t = 0xFFFFFFFF
    min_w: uint32_t = MIN_WIDTH
    valid: uint1_t = ~rst  # BLOCK, as pdw_main gates the detector's input
    d = _DP(
        in_stream=_DP.in_stream_t(pulse_sample(n), valid),
        pdw_out_if=_DP.out_fb_t(1),
        threshold_high=_DP.power_t(val=THR_HI),
        threshold_low=_DP.power_t(val=THR_LO),
        max_width=max_w,
    )
    e = _ENG(
        gated_in=d.gated_out,
        pdw_in_if=d.pdw_out_if,
        dsp_overflow=d.overflow,
        min_width=min_w,
        max_width=max_w,
        freq_acc=d.freq_acc,
        noise_est=d.noise_est,
        pkt_out_if=_ENG.pkt_out_intrf.fb_t(1),
        pdw_out_if=_ENG.pdw_out_intrf.fb_t(1),
    )
    o.pdw = e.pdw_out_if.stream
    o.pkt = e.pkt_out_if.stream
    n += 1

    # -- pdw_ctrl: POISON and an abandoned prefix before the reset, CFG_B after
    poison_w: uint32_t[N_BEATS] = POISON_W
    cfg_w: uint32_t[N_BEATS] = CFG_B_W
    word: uint32_t = 0
    beat: uint1_t = 0
    last: uint1_t = 0
    if t < RESET_AT:
        if (t >= POISON_AT) & (t < POISON_AT + N_BEATS):
            k: uint16_t = t - POISON_AT
            word = frame_beat(poison_w, k)
            beat = 1
            last = k == N_BEATS - 1
        elif t >= PARTIAL_AT:
            word = frame_beat(poison_w, t - PARTIAL_AT)
            beat = 1
    elif t > RESET_AT:
        if (m >= CFG_B_AT) & (m < CFG_B_AT + N_BEATS):
            j: uint16_t = m - CFG_B_AT
            word = frame_beat(cfg_w, j)
            beat = 1
            last = j == N_BEATS - 1
    keep_all: uint4_t = 15
    ci: ctrl.axis_intrf.stream_t
    ci.data.frag.data = uint_to_array_le(word, 8)
    ci.data.frag.keep = uint_to_array_le(keep_all, 1)
    ci.data.eod[0] = last
    ci.valid = beat
    c = ctrl(axis_in_if=ctrl.axis_intrf.fwd_t(ci))
    o.regs = c.regs
    o.ctrl_ready = c.axis_in_if.ready

    # -- alarm: one in flight at the reset, one after it --------------------
    trig: uint1_t = 0
    if t < RESET_AT:
        trig = t == ALARM_PRE_AT
    elif t > RESET_AT:
        trig = m == ALARM_POST_AT
    o.alarm = alarm(trig=trig, en=1, in_valid=1)
    m += 1
    return o


clk = make_clock(125.0)
rst_a: Wire[uint1_t] = make_reset()
rst_b: Wire[uint1_t] = make_reset()
t_out: Wire[uint16_t]
a_out: Wire[tb_out_t]
b_out: Wire[tb_out_t]


@MAIN(clk)
def rst_gen():
    t: Reg[uint16_t]
    rst_a = t == RESET_AT
    rst_b = t <= RESET_AT
    t_out = t
    t += 1


@MAIN(clk, reset=rst_a, reset_registers="all")
def dut_a():
    a_out = pdw_blocks(rst_a, t_out)


@MAIN(clk, reset=rst_b, reset_registers="all")
def dut_b():
    b_out = pdw_blocks(rst_b, t_out)


@hw_func
def pdw_equal(x: pdw_stream_t, y: pdw_stream_t) -> uint1_t:
    # Data compared only with valid
    same: uint1_t = (
        (x.data.toa == y.data.toa)
        & (x.data.pulse_width == y.data.pulse_width)
        & (x.data.peak_power == y.data.peak_power)
        & (x.data.pkt_samples == y.data.pkt_samples)
        & (x.data.pri == y.data.pri)
        & (x.data.peak_power_db == y.data.peak_power_db)
        & (x.data.noise_power_db == y.data.noise_power_db)
        & (x.data.freq_start == y.data.freq_start)
        & (x.data.freq_stop == y.data.freq_stop)
        & (x.data.status_flags == y.data.status_flags)
    )
    rv: uint1_t = x.valid == y.valid
    if x.valid:
        rv = rv & same
    return rv


@hw_func
def pkt_equal(x: pkt_stream_t, y: pkt_stream_t) -> uint1_t:
    same: uint1_t = (
        (x.data.sample.i.val == y.data.sample.i.val)
        & (x.data.sample.q.val == y.data.sample.q.val)
        & (x.data.last == y.data.last)
    )
    rv: uint1_t = x.valid == y.valid
    if x.valid:
        rv = rv & same
    return rv


@hw_func
def regs_equal(x: pdw_ctrl_t, y: pdw_ctrl_t) -> uint1_t:
    return (
        (x.pulse_gen_pri == y.pulse_gen_pri)
        & (x.pulse_gen_width == y.pulse_gen_width)
        & (x.pulse_gen_freq == y.pulse_gen_freq)
        & (x.pulse_gen_chirp_rate == y.pulse_gen_chirp_rate)
        & (x.pulse_gen_amplitude == y.pulse_gen_amplitude)
        & (x.pulse_gen_noise_amp == y.pulse_gen_noise_amp)
        & (x.threshold_high == y.threshold_high)
        & (x.threshold_low == y.threshold_low)
        & (x.max_width == y.max_width)
        & (x.min_width == y.min_width)
        & (x.flags == y.flags)
    )


def make_regs_are(cfg):
    """regs_are(x): x holds cfg. A module-global struct is not a hardware
    value, but its fields fold to literals."""

    @hw_func
    def regs_are(x: pdw_ctrl_t) -> uint1_t:
        return (
            (x.pulse_gen_pri == cfg.pulse_gen_pri)
            & (x.pulse_gen_width == cfg.pulse_gen_width)
            & (x.pulse_gen_freq == cfg.pulse_gen_freq)
            & (x.pulse_gen_chirp_rate == cfg.pulse_gen_chirp_rate)
            & (x.pulse_gen_amplitude == cfg.pulse_gen_amplitude)
            & (x.pulse_gen_noise_amp == cfg.pulse_gen_noise_amp)
            & (x.threshold_high == cfg.threshold_high)
            & (x.threshold_low == cfg.threshold_low)
            & (x.max_width == cfg.max_width)
            & (x.min_width == cfg.min_width)
            & (x.flags == cfg.flags)
        )

    return regs_are


regs_are_defaults = make_regs_are(CTRL_DEFAULTS)
regs_are_cfg_b = make_regs_are(CFG_B)


@MAIN(clk)
def checker():
    t: uint16_t = t_out
    a: tb_out_t = a_out
    b: tb_out_t = b_out
    n_pdw: Reg[uint8_t]
    n_pkt: Reg[uint8_t]
    beats: Reg[uint16_t]
    want_beats: Reg[uint32_t]
    low: Reg[uint16_t]
    if t == N_CYCLES + 1:
        sim_assert(n_pdw == 2, f"{n_pdw} PDWs after the reset, expected pulses 1 and 2")
        sim_assert(n_pkt == 2, f"{n_pkt} packets after the reset, expected 2")
        sim_assert(low == DROPS, f"the alarm after the reset dropped {low} samples")
        sim_finish()
    if t == RESET_AT:
        sim_assert(a.regs.threshold_high == POISON.threshold_high,
                   "the POISON frame did not apply before the reset")
        sim_assert(b.regs.threshold_high == CTRL_DEFAULTS.threshold_high,
                   "a frame applied while its block was in reset")
        sim_assert(a.alarm.active == 1, "no alarm in flight at the reset")
        sim_assert(n_pdw == 0, "the interrupted pulse closed before the reset")
    if (t > RESET_AT) & (t <= N_CYCLES):
        sim_assert(pdw_equal(a.pdw, b.pdw), f"PDW differs at {t}")
        sim_assert(pkt_equal(a.pkt, b.pkt), f"packet beat differs at {t}")
        sim_assert(regs_equal(a.regs, b.regs), f"control registers differ at {t}")
        sim_assert(a.ctrl_ready == 1, f"control ready low at {t}")
        sim_assert((a.alarm.ready == b.alarm.ready) & (a.alarm.active == b.alarm.active)
                   & (a.alarm.firing == b.alarm.firing), f"alarm differs at {t}")
        if t < CFG_B_APPLIED:
            sim_assert(regs_are_defaults(a.regs),
                       f"control registers are not CTRL_DEFAULTS at {t}")
        else:
            sim_assert(regs_are_cfg_b(a.regs), f"CFG_B did not apply by {t}")
        if a.alarm.ready == 0:
            low += 1
        if a.pdw.valid:
            pri_bad: uint32_t = a.pdw.data.status_flags & STATUS_PRI_INVALID
            if n_pdw == 0:
                sim_assert(pri_bad != 0, "the first pulse after the reset reports a PRI")
                sim_assert(a.pdw.data.toa < P1_AT + PULSE_W + 8,
                           f"TOA {a.pdw.data.toa} not counted from the reset")
            else:
                sim_assert(pri_bad == 0, "the second pulse after the reset has no PRI")
            want_beats = a.pdw.data.pkt_samples
            n_pdw += 1
            sim_print(
                f"t={t} pdw toa={a.pdw.data.toa} width={a.pdw.data.pulse_width} "
                f"samples={a.pdw.data.pkt_samples} pri={a.pdw.data.pri} "
                f"flags={a.pdw.data.status_flags} f={a.pdw.data.freq_start} "
                f"db={a.pdw.data.peak_power_db}",
                debug=True,
            )
        if a.pkt.valid:
            sim_print(f"t={t} pkt {a.pkt.data.sample.i.val} {a.pkt.data.sample.q.val} "
                      f"last={a.pkt.data.last}", debug=True)
            if a.pkt.data.last:
                sim_assert(beats + 1 == want_beats,
                           f"packet of {beats + 1} beats, its PDW says {want_beats}")
                n_pkt += 1
                beats = 0
            else:
                beats += 1
        if (t == RESET_AT + 1) | (t == CFG_B_APPLIED):
            # Low 16 bits: a VHDL sim_print of 2^31 or more overflows (#360)
            thr16: uint16_t = a.regs.threshold_high[15:0]
            sim_print(f"t={t} regs thr_hi16={thr16} pri={a.regs.pulse_gen_pri}", debug=True)
