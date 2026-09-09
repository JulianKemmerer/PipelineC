#!/usr/bin/env python3
"""Reset semantics for the PDW datapath: block, DRAIN, clear.

../pdw_tb.py exercises reset at power-on, where there is nothing buffered and
so nothing to clean up. The interesting case is a reset that lands MID-PULSE,
with a partly-written packet in the data FIFO, a descriptor never pushed, and
the hysteresis SM sitting in PULSE. That is what this file drives.

WHY A DRAIN AT ALL. The three FIFOs in packet_store and Path B's delay line are
`make_fifo` instances -- black-box wrappers over pipelinec_fifo_fwft.vhd with
only push/pop, no flush, no pointers. A reset signal cannot clear them. The only
way to empty one is to clock its contents out, which is what reset does by
forcing every read enable high for the length of the reset. `pkt_out_ready` is
driven LOW throughout the reset window here, precisely so that the consumer
cannot be what empties the FIFO: if the `| rst` term in packet_store's
`data_ready` were removed, nothing would.

WHY DRAINING IS NOT ENOUGH ON ITS OWN. `data_ready`'s other two terms both
require a descriptor to have been popped, and the pulse this test interrupts
never pushed one (`desc_push = gated_in.valid & gated_in.last` never fires for a
pulse that is still open). Those samples are unreachable by the normal release
path, which is why the reset term exists and why test_no_leak_across_reset
checks the NEXT packet's contents rather than just its length.

Composed with sim_call rather than a pipelinec build: the blocks under test are
pulse_detect and pulse_extract wired exactly as top.py wires them, and driving
them directly costs seconds instead of the ~18 minutes a full top.py native sim
takes. The reset's effect on the AXIS serializers is covered separately, by
pdw_tb.py's check_reset (no master tvalid during reset) and by
pdw_ctrl_test.py's flush tests.

Run: python3 pdw_reset_test.py
"""

import pdw_paths  # noqa: F401  (puts include/pypeline on sys.path)

from pypeline import sim_call, sim_reset

from dsp.dsp_tb import golden_dc_block, golden_magnitude, golden_moving_avg
from pulse_extract import STATUS_PRI_INVALID, make_pulse_extract
from pulse_detect import make_pulse_detect

# Small FIFOs: this test's packets are tens of beats, and a shallow data FIFO
# makes a failed drain show up as a full FIFO rather than as slack space.
TB_DEPTH = 512
TB_N_PKTS = 8

_DP, _ = make_pulse_detect()
_ENG, _ = make_pulse_extract(_DP, depth=TB_DEPTH, n_pkts=TB_N_PKTS)

CPLX = _DP.complex_t
RAIL = _DP.rail_t
PWR = _DP.power_t

AMPLITUDE = 12000
PULSE_W = 40
IDLE = 120  # >= the DSP chain's fill plus room for the noise estimator

# Two pulses with a long gap, and a reset window that starts inside the first
# and ends well before the second. Named rather than computed inline because
# every test below depends on the second pulse being wholly OUTSIDE the reset
# -- an overlap would make a passing test mean nothing (it did, once).
P1_AT = IDLE
P2_AT = IDLE * 2 + PULSE_W
RST_AT = P1_AT + PULSE_W // 2  # mid-pulse: packet part written, no descriptor
RST_LEN = 100  # >> the ~40 beats buffered; the drain runs at one per cycle
assert RST_AT + RST_LEN + IDLE // 4 < P2_AT, (
    "the reset window would swallow the second pulse, so 'nothing came out' "
    "would pass for the wrong reason"
)

# Glitch rejection, and it is doing real work here rather than being scenery.
# magnitude, dc_block and moving_avg live in include/pypeline/dsp/ -- library
# code this project does not put a reset into -- so they FREEZE holding
# mid-pulse power when reset gates their input valid, and thaw still holding it.
# For a sample or two after release the conditioned power therefore reads high
# and the hysteresis SM declares a tiny pulse that never happened.
#
# min_width is exactly the mechanism for that, and it is why the artifact is a
# documented consequence rather than a defect: a deployment that sets min_width
# at all never sees it. test_release_artifact_is_a_rejected_glitch pins its size
# so this number stays justified instead of merely large enough.
MIN_WIDTH = 8


def _stimulus(pulses):
    """(i, q) per sample for a list of (start, width) pulses. Q is a quarter
    period out of phase with I so the phasor is not degenerate -- a pure DC
    step would make every frequency measurement trivially zero."""
    n = max(s + w for s, w in pulses) + IDLE
    out = [(0, 0)] * n
    for start, width in pulses:
        for k in range(width):
            # A slow rotation: four samples per turn.
            i, q = [(AMPLITUDE, 0), (0, AMPLITUDE), (-AMPLITUDE, 0),
                    (0, -AMPLITUDE)][k % 4]
            out[start + k] = (i, q)
    return out


def _thresholds(raw):
    """Pick thresholds from the real conditioned power, so this test does not
    depend on dc_block/moving_avg's internal scaling staying put."""
    power = golden_moving_avg(
        _DP.moving_avg, golden_dc_block(_DP.dc_block, golden_magnitude(
            _DP.magnitude, raw))
    )
    peak = max(power)
    assert peak > 0, "stimulus produced no power at all"
    return peak // 2, peak // 4


class _Run:
    """One pass of pulse_detect -> pulse_extract, wired as top.py wires them."""

    def __init__(self, raw, rst_of, thr_hi, thr_lo, min_width=MIN_WIDTH,
                 max_width=0xFFFFFFFF, pkt_ready_of=None, n_extra=400):
        self.pdws = []  # (cycle, dict) per emitted valid_pdw
        self.pkts = []  # [(i, q), ...] per released packet
        self.rst_cycles = 0
        sim_reset()
        cur = []
        for c in range(len(raw) + n_extra):
            rst = 1 if rst_of(c) else 0
            self.rst_cycles += rst
            i, q = raw[c] if c < len(raw) else (0, 0)
            # BLOCK, exactly as top.py's pdw_main does it: one gate on the
            # detector's input valid stops both Path A and Path B.
            valid = 0 if (rst or c >= len(raw)) else 1
            o = sim_call(
                _DP,
                in_stream=_DP.in_stream_t(
                    data=CPLX(i=RAIL(val=i), q=RAIL(val=q)), valid=valid
                ),
                pdw_out_if=_DP.out_fb_t(1),
                threshold_high=PWR(val=thr_hi),
                threshold_low=PWR(val=thr_lo),
                max_width=max_width,
                rst=rst,
            )
            # The consumer is NOT ready during reset -- see the module
            # docstring. Outside reset it is always ready.
            pkt_ready = 0 if rst else (
                1 if pkt_ready_of is None else int(pkt_ready_of(c))
            )
            e = sim_call(
                _ENG,
                gated_in=o.gated_out,
                pdw_in_if=o.pdw_out_if,
                dsp_overflow=o.overflow,
                min_width=min_width,
                max_width=max_width,
                freq_acc=o.freq_acc,
                noise_est=o.noise_est,
                pkt_out_if=_ENG.pkt_out_intrf.fb_t(pkt_ready),
                pdw_out_if=_ENG.pdw_out_intrf.fb_t(1),
                rst=rst,
            )
            # top.py gates every master tvalid with ~rst, so ignore the engine's
            # outputs while reset is asserted -- they are mid-drain and nothing
            # they carry reaches a port. Deliberately NOT asserted to be idle
            # here: draining is exactly the engine emitting beats into the bit
            # bucket, so "quiet during reset" would be the wrong expectation.
            # That no drain traffic escapes is checked where it is true, on the
            # real ports, by pdw_tb.py's check_reset.
            if rst:
                continue
            pdw = e.pdw_out_if.stream
            pkt = e.pkt_out_if.stream
            if int(pdw.valid):
                self.pdws.append((c, {
                    "toa": int(pdw.data.toa),
                    "pulse_width": int(pdw.data.pulse_width),
                    "pkt_samples": int(pdw.data.pkt_samples),
                    "pri": int(pdw.data.pri),
                    "status_flags": int(pdw.data.status_flags),
                }))
            if int(pkt.valid) and pkt_ready:
                cur.append((int(pkt.data.sample.i.val),
                            int(pkt.data.sample.q.val)))
                if int(pkt.data.last):
                    self.pkts.append(cur)
                    cur = []
        assert not cur, f"a packet was left unterminated: {len(cur)} beats"


def _baseline():
    """Two pulses, no reset -- what the reset runs are compared against.

    Real pulses are PULSE_W samples, far above MIN_WIDTH, so glitch rejection
    changes nothing here; it only removes the release artifact."""
    raw = _stimulus([(P1_AT, PULSE_W), (P2_AT, PULSE_W)])
    hi, lo = _thresholds(raw)
    return raw, hi, lo, _Run(raw, lambda c: False, hi, lo)


def test_baseline_two_pulses():
    """The control case. Without it a reset test could 'pass' by producing
    nothing at all, which is exactly the wrong kind of success."""
    _raw, _hi, _lo, r = _baseline()
    assert len(r.pdws) == 2, f"expected 2 PDWs with no reset, got {len(r.pdws)}"
    assert len(r.pkts) == 2, f"expected 2 packets, got {len(r.pkts)}"
    # Not exactly PULSE_W, and the two are not exactly equal either: moving_avg
    # and dc_block smear the envelope, and dc_block's mean is a CONTINUOUS IIR
    # state across the run, so the second pulse's trailing edge crosses
    # threshold_low a sample earlier than the first. Both are the detector
    # working as designed. Every reset assertion below therefore compares the
    # same pulse in the same position against this run, never a nominal value.
    for _c, p in r.pdws:
        assert abs(p["pulse_width"] - PULSE_W) <= 4, (
            f"measured width {p['pulse_width']} is not within smearing "
            f"distance of the {PULSE_W} samples actually driven"
        )
    # First accepted pulse has no predecessor to measure against.
    assert r.pdws[0][1]["status_flags"] & STATUS_PRI_INVALID, r.pdws[0][1]
    assert not (r.pdws[1][1]["status_flags"] & STATUS_PRI_INVALID), r.pdws[1][1]
    assert r.pdws[1][1]["pri"] > 0, r.pdws[1][1]
    print(f"test_baseline_two_pulses passed "
          f"({len(r.pkts[0])}-beat packets, pri={r.pdws[1][1]['pri']})")


def test_mid_pulse_reset_emits_nothing():
    """A reset asserted inside a pulse must leave no trace of it: no PDW, no
    packet, not even a partial one."""
    raw, hi, lo, base = _baseline()
    # Reset lands a few samples into the FIRST pulse, so a packet is part
    # written and its descriptor has not been pushed.
    r = _Run(raw, lambda c: RST_AT <= c < RST_AT + RST_LEN, hi, lo)
    # Only the SECOND pulse survives -- it is entirely after the reset window.
    assert len(r.pdws) == 1, (
        f"expected exactly 1 PDW (the post-reset pulse), got {len(r.pdws)}: "
        f"{[p for _c, p in r.pdws]}"
    )
    assert len(r.pkts) == 1, f"expected 1 packet, got {len(r.pkts)}"
    assert r.pdws[0][1]["pulse_width"] == base.pdws[1][1]["pulse_width"], (
        f"the post-reset pulse measured differently from the same pulse in an "
        f"un-reset run: {r.pdws[0][1]} vs {base.pdws[1][1]}"
    )
    print("test_mid_pulse_reset_emits_nothing passed")


def test_no_leak_across_reset():
    """The interrupted pulse's SAMPLES must not survive either.

    This is the assertion the drain exists for. Those samples sit in the data
    FIFO with no descriptor, so the normal release path can never reach them --
    without `data_ready |= rst` they stay there and become the head of the next
    packet, which then has the right length but the wrong contents.

    Verified to fail with that term removed."""
    raw, hi, lo, base = _baseline()
    r = _Run(raw, lambda c: RST_AT <= c < RST_AT + RST_LEN, hi, lo)
    assert len(r.pkts) == 1
    got, want = r.pkts[0], base.pkts[1]
    assert len(got) == len(want), (
        f"post-reset packet is {len(got)} beats, the same pulse without a "
        f"reset is {len(want)} -- the interrupted pulse's samples were "
        f"prepended rather than drained"
    )
    assert got == want, (
        "post-reset packet contents differ from the same pulse driven without "
        f"a reset:\n  got  {got[:6]}...\n  want {want[:6]}..."
    )
    print(f"test_no_leak_across_reset passed ({len(got)} beats, byte-exact)")


def test_toa_and_pri_restart():
    """toa_counter is cleared by reset, so pulse_measure's prev_toa/have_prev
    must be cleared with it -- otherwise the first pulse after release computes
    `toa - prev_toa` across two counter epochs and reports a wrapped, enormous
    PRI as if it were real."""
    raw, hi, lo, base = _baseline()
    r = _Run(raw, lambda c: RST_AT <= c < RST_AT + RST_LEN, hi, lo)
    p = r.pdws[0][1]
    assert p["status_flags"] & STATUS_PRI_INVALID, (
        f"the first pulse after a reset must report PRI invalid, not a PRI "
        f"measured against a pre-reset TOA: {p}"
    )
    # TOA counts accepted samples since release, so it must be far below the
    # value the same pulse carries in a run that was never reset.
    assert p["toa"] < base.pdws[1][1]["toa"], (
        f"toa did not restart at reset: {p['toa']} vs an un-reset "
        f"{base.pdws[1][1]['toa']}"
    )
    print(f"test_toa_and_pri_restart passed (toa {p['toa']} vs "
          f"{base.pdws[1][1]['toa']} un-reset, PRI reported invalid)")


def test_release_artifact_is_a_rejected_glitch():
    """Document, and bound, the one thing reset cannot clean up.

    magnitude/dc_block/moving_avg are library blocks with no reset, so they
    freeze holding mid-pulse power and thaw still holding it. With glitch
    rejection disabled (min_width=1) that shows up as a spurious few-sample
    pulse right after release. This test asserts it exists, asserts it is
    SMALL, and asserts MIN_WIDTH is comfortably above it -- so the constant the
    other tests rely on is a measured bound rather than a guess, and a future
    change that made the artifact longer would fail here rather than silently
    start leaking real-looking PDWs."""
    raw, hi, lo, base = _baseline()
    r = _Run(raw, lambda c: RST_AT <= c < RST_AT + RST_LEN, hi, lo, min_width=1)
    assert len(r.pdws) == 2, (
        f"expected the release artifact plus the real pulse, got "
        f"{[p for _c, p in r.pdws]}"
    )
    art = r.pdws[0][1]
    real = r.pdws[1][1]
    assert real["pulse_width"] == base.pdws[1][1]["pulse_width"], (
        f"the real post-reset pulse was distorted: {real}"
    )
    assert art["pulse_width"] < MIN_WIDTH, (
        f"the release artifact is {art['pulse_width']} samples, which "
        f"MIN_WIDTH={MIN_WIDTH} no longer rejects -- either shorten the "
        f"artifact or raise MIN_WIDTH, but do not leave it unrejected"
    )
    # It is an artifact of the conditioning chain, not a fragment of the
    # interrupted pulse: its TOA is counted from release, not carried over.
    assert art["toa"] < art["pulse_width"] + 4, (
        f"the artifact carries a pre-reset TOA, so it is leaked state rather "
        f"than a fresh mis-detection: {art}"
    )
    print(f"test_release_artifact_is_a_rejected_glitch passed "
          f"({art['pulse_width']} samples < MIN_WIDTH={MIN_WIDTH})")


def test_reset_between_pulses_is_clean():
    """Reset in an idle gap -- nothing buffered, nothing open. The pulse after
    it must come out exactly as it does with no reset at all, which is what
    says the clears do not damage a design that had nothing to clean up."""
    raw, hi, lo, base = _baseline()
    gap = P1_AT + PULSE_W + 20
    r = _Run(raw, lambda c: gap <= c < gap + 60, hi, lo)
    assert len(r.pkts) == 1, f"expected 1 packet, got {len(r.pkts)}"
    assert r.pkts[0] == base.pkts[1], (
        "a reset in an idle gap changed the following pulse's packet"
    )
    print("test_reset_between_pulses_is_clean passed")


if __name__ == "__main__":
    print(f"pdw_reset_test: depth={TB_DEPTH} n_pkts={TB_N_PKTS} "
          f"amplitude={AMPLITUDE} width={PULSE_W}")
    test_baseline_two_pulses()
    test_mid_pulse_reset_emits_nothing()
    test_no_leak_across_reset()
    test_toa_and_pri_restart()
    test_release_artifact_is_a_rejected_glitch()
    test_reset_between_pulses_is_clean()
    print("All pdw_reset tests passed")
