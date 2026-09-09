#!/usr/bin/env python3
"""Unit test for pdw_ctrl.py: the AXIS-written control register file.

../pdw_tb.py exercises this block inside the whole pipeline, but only with
well-formed frames arriving at convenient moments. This drives it directly with
the malformed traffic a real host eventually produces -- short writes, padded
writes, back-to-back writes -- and pins the two properties pdw_tb.py depends on
and cannot itself check:

  * `ready` is NEVER low, so a frame's beats always land on consecutive cycles
    and the apply moment is a pure function of when it was sent;
  * `latency` is exactly what the module advertises, so pdw_tb.py's schedule
    switching stays aligned with the hardware without hardcoding a number.

A malformed frame must leave the registers untouched AND not desync the frames
that follow it -- the second half is the part that is easy to get wrong and
invisible until a host pads one write.

Run: python3 pdw_ctrl_test.py
"""

import pdw_paths  # noqa: F401  (puts include/pypeline on sys.path)

from pypeline import sim_call, sim_reset, type_to_bytes

from axi.axis_sim import AxisSimSource
from pdw_ctrl import (
    CTRL_DEFAULTS,
    CTRL_FLAG_LOOPBACK_EN,
    CTRL_N_BYTES,
    make_pdw_ctrl,
    pdw_ctrl_t,
)

N = 4
ctrl, ctrl_t = make_pdw_ctrl(N)
FIELDS = pdw_ctrl_t._fields

CFG_A = pdw_ctrl_t(
    pulse_gen_pri=4096,
    pulse_gen_width=200,
    pulse_gen_freq=1 << 29,
    pulse_gen_chirp_rate=-12345,
    pulse_gen_amplitude=9000,
    pulse_gen_noise_amp=17,
    threshold_high=500000,
    threshold_low=250000,
    max_width=3000,
    min_width=12,
    flags=CTRL_FLAG_LOOPBACK_EN,
)
CFG_B = pdw_ctrl_t(
    pulse_gen_pri=777,
    pulse_gen_width=64,
    pulse_gen_freq=-(1 << 28),
    pulse_gen_chirp_rate=99,
    pulse_gen_amplitude=-4321,
    pulse_gen_noise_amp=3,
    threshold_high=88888,
    threshold_low=44444,
    max_width=999,
    min_width=5,
    flags=0,
)


def _regs(r):
    return {f: int(getattr(r.regs, f)) for f in FIELDS}


def _want(cfg):
    return {f: int(getattr(cfg, f)) for f in FIELDS}


def _run(script, n_cycles, dut=None, rst_until=0):
    """script: {cycle: bytes} frames to start. Returns one dict per cycle.

    `rst_until`: hold rst high for cycles [0, rst_until). Note the block is
    reset from tx0_s_axis_rst ALONE, not the design's global reset -- being
    able to bring this block up on its own is the point (see pdw_ctrl.py).
    """
    dut = dut or ctrl
    sim_reset()
    src = AxisSimSource(dut.axis_intrf, N)
    log = []
    for c in range(n_cycles):
        if c in script:
            assert src.idle(), f"cycle {c}: previous frame still in flight"
            src.send(script[c])
        # ready is checked (not consumed) below: the block promises it is always
        # 1, so driving the source with 1 unconditionally is only legitimate
        # because every cycle's real value is asserted to be 1.
        word_if = src.step(1)
        rst = 1 if c < rst_until else 0
        r = sim_call(dut, axis_in_if=word_if, rst=rst)
        log.append(
            {
                "ready": int(r.axis_in_if.ready),
                "updated": int(r.updated),
                "runt": int(r.runt),
                "valid_in": int(word_if.stream.valid),
                "last_in": int(word_if.stream.data.eod[0]),
                "rst": rst,
                "regs": _regs(r),
            }
        )
    return log


def test_defaults_at_reset():
    log = _run({}, 6)
    for c, s in enumerate(log):
        assert s["regs"] == _want(CTRL_DEFAULTS), f"cycle {c}: {s['regs']}"
        assert s["updated"] == 0 and s["runt"] == 0, f"cycle {c}: {s}"
    print("test_defaults_at_reset passed")


def test_ready_is_always_high():
    """The whole apply-timing contract rests on this. A single low cycle would
    stretch a frame and silently shift every downstream expectation."""
    log = _run({1: type_to_bytes(pdw_ctrl_t, CFG_A),
                20: type_to_bytes(pdw_ctrl_t, CFG_B)}, 40)
    low = [c for c, s in enumerate(log) if not s["ready"]]
    assert not low, f"ready went low on cycles {low}"
    print("test_ready_is_always_high passed")


def _measure_latency(dut, cfg):
    """Observed cycles from "last beat accepted" to "new values readable"."""
    log = _run({3: type_to_bytes(pdw_ctrl_t, cfg)}, 30, dut=dut)
    last = max(c for c, s in enumerate(log) if s["valid_in"])
    readable = [c for c, s in enumerate(log) if s["regs"] == _want(cfg)]
    assert readable, "the frame never applied at all"
    return last, readable[0] - last, log


def test_exact_frame_applies_after_last_beat():
    start = 3
    last, observed, log = _measure_latency(ctrl, CFG_A)

    beats = [c for c, s in enumerate(log) if s["valid_in"]]
    assert beats == list(range(start, start + ctrl.n_beats)), (
        f"frame should occupy {ctrl.n_beats} consecutive cycles, got {beats}"
    )
    assert log[last]["last_in"] == 1, "tlast must land on the final beat"
    assert len([c for c, s in enumerate(log) if s["updated"]]) == 1, (
        "exactly one update per frame"
    )
    # The advertised latency must be the MEASURED one -- pdw_tb.py schedules
    # every phase change against this attribute, so a silent drift here would
    # skew every downstream expectation in the whole pipeline testbench.
    assert observed == ctrl.latency, (
        f"pdw_ctrl.latency says {ctrl.latency}, hardware takes {observed} "
        f"(last beat cycle {last})"
    )
    # OLD values still visible until then -- i.e. the update really is
    # registered, not combinational.
    for c in range(last, last + observed):
        assert log[c]["regs"] == _want(CTRL_DEFAULTS), (
            f"registers changed early, at cycle {c}"
        )
    for c in range(last + observed, len(log)):
        assert log[c]["regs"] == _want(CFG_A), f"cycle {c} did not hold"
    print(f"test_exact_frame_applies_after_last_beat passed (latency {observed})")


def test_latency_is_independent_of_registered_ready():
    """`registered_ready=True` is the documented escape hatch if the ready path
    ever needs breaking for timing. It must not move the apply moment, or
    reaching for it would silently invalidate pdw_tb.py."""
    rr, _ = make_pdw_ctrl(N, registered_ready=True)
    _, observed, _ = _measure_latency(rr, CFG_A)
    assert observed == rr.latency == ctrl.latency, (
        f"registered_ready changed the apply latency: {observed} vs {ctrl.latency}"
    )
    print("test_latency_is_independent_of_registered_ready passed")


def test_back_to_back_frames_both_apply():
    a, b = 2, 2 + ctrl.n_beats
    log = _run({a: type_to_bytes(pdw_ctrl_t, CFG_A),
                b: type_to_bytes(pdw_ctrl_t, CFG_B)}, 40)
    ups = [c for c, s in enumerate(log) if s["updated"]]
    assert len(ups) == 2, f"expected 2 updates, got {ups}"
    # CFG_A must be visible for a whole cycle before CFG_B replaces it: two
    # writes with no gap must not collapse into one.
    lasts = [a + ctrl.n_beats - 1, b + ctrl.n_beats - 1]
    assert log[lasts[0] + ctrl.latency]["regs"] == _want(CFG_A), "CFG_A skipped"
    assert log[lasts[1] + ctrl.latency]["regs"] == _want(CFG_B), "CFG_B lost"
    print("test_back_to_back_frames_both_apply passed")


def test_oversized_frame_drops_padding():
    """A host (or an Ethernet minimum-frame pad) appending bytes must not shift
    the struct, and must not leave a residue that desyncs the NEXT frame."""
    padded = type_to_bytes(pdw_ctrl_t, CFG_A) + b"\xAA" * 8
    log = _run({1: padded, 30: type_to_bytes(pdw_ctrl_t, CFG_B)}, 60)

    ups = [c for c, s in enumerate(log) if s["updated"]]
    assert len(ups) == 2, f"expected exactly 2 updates, got {ups}"
    assert log[ups[0] + ctrl.latency]["regs"] == _want(CFG_A), (
        "padding was decoded as struct content"
    )
    assert log[ups[1] + ctrl.latency]["regs"] == _want(CFG_B), (
        "the frame AFTER the padded one was desynced by its residue"
    )
    print("test_oversized_frame_drops_padding passed")


def test_runt_frame_is_discarded():
    """A truncated write must leave the registers wholly untouched -- never
    half-applied -- and must not consume part of the next frame."""
    runt = type_to_bytes(pdw_ctrl_t, CFG_A)[: CTRL_N_BYTES - 4]
    log = _run({1: runt, 30: type_to_bytes(pdw_ctrl_t, CFG_B)}, 60)

    ups = [c for c, s in enumerate(log) if s["updated"]]
    assert len(ups) == 1, f"a runt frame must not update the registers: {ups}"
    assert any(s["runt"] for s in log), "the discarded runt was not flagged"
    # Everything before the good frame lands still reads the reset defaults.
    assert log[ups[0]]["regs"] == _want(CTRL_DEFAULTS), (
        "the runt frame partially applied"
    )
    assert log[ups[0] + ctrl.latency]["regs"] == _want(CFG_B), (
        "the frame after the runt was desynced"
    )
    print("test_runt_frame_is_discarded passed")


def test_reset_holds_defaults():
    """A well-formed frame written while rst is high must be refused. This is
    the whole reason the block has a reset: an unconfigured device must present
    the safe defaults (max thresholds, silent generator), not whatever a host
    wrote before it was ready to be listened to."""
    frame = type_to_bytes(pdw_ctrl_t, CFG_A)
    # Frame at cycle 1 lands well inside the reset window.
    log = _run({1: frame}, 40, rst_until=1 + ctrl.n_beats + ctrl.latency + 4)
    in_rst = [s for s in log if s["rst"]]
    assert in_rst, "test drove no reset cycles"
    for c, s in enumerate(log):
        if s["rst"]:
            assert s["regs"] == _want(CTRL_DEFAULTS), (
                f"cycle {c}: a frame applied while in reset: {s['regs']}"
            )
    # And it stays refused after release -- the frame is gone, not deferred.
    for c, s in enumerate(log):
        if not s["rst"]:
            assert s["regs"] == _want(CTRL_DEFAULTS), (
                f"cycle {c}: a frame written during reset applied after "
                f"release: {s['regs']}"
            )
    print("test_reset_holds_defaults passed")


def test_frame_applies_after_reset_release():
    """Reset must leave nothing behind: the next frame applies normally, on
    exactly the usual schedule. Pairs with the test above -- together they say
    reset refuses writes without also breaking the port."""
    rst_until = 8
    start = rst_until + 2
    log = _run({start: type_to_bytes(pdw_ctrl_t, CFG_B)}, 40, rst_until=rst_until)
    last = max(c for c, s in enumerate(log) if s["valid_in"])
    got = log[last + ctrl.latency]["regs"]
    assert got == _want(CFG_B), (
        f"frame after reset release did not apply on schedule: {got}"
    )
    print("test_frame_applies_after_reset_release passed")


def _beat(dut, chunk, last):
    """One hand-built AXIS beat. AxisSimSource always terminates the bytes it
    is given with tlast, which makes a short frame a RUNT -- something the
    deserializer's on_eod="discard" already handles. Reproducing an ABANDONED
    frame, the case reset actually has to clean up, means driving beats that
    carry no tlast at all, so they are built here rather than sent."""
    stream_t = dut.axis_intrf.stream_t
    frag_t = stream_t.typeof("data")
    bus_t = frag_t.typeof("frag")
    data = [0] * N
    keep = [0] * N
    for i, b in enumerate(chunk):
        data[i] = b
        keep[i] = 1
    return dut.axis_intrf.fwd_t(
        stream_t(
            data=frag_t(frag=bus_t(data=data, keep=keep), eod=[1 if last else 0]),
            valid=1,
        )
    )


def test_reset_flushes_an_abandoned_frame():
    """The deserializer must not carry bytes across a reset.

    A host torn down mid-DMA leaves a byte prefix behind with NO tlast ever
    arriving -- and the limiter's and deserializer's counters clear only on a
    real eod. Without the flush in pdw_ctrl, the next frame's bytes complete
    that prefix into a struct that is wrong but perfectly well formed: applied
    silently, no runt, no error. That is strictly worse than a dropped write,
    which is why it is tested rather than assumed.

    Verified to fail with the flush disabled."""
    stale = type_to_bytes(pdw_ctrl_t, CFG_A)
    good = type_to_bytes(pdw_ctrl_t, CFG_B)
    n_stale = 3  # beats of a frame that is then abandoned, no tlast
    rst_from, rst_until = n_stale, 20
    start = rst_until + 2

    sim_reset()
    src = AxisSimSource(ctrl.axis_intrf, N)
    log = []
    for c in range(60):
        if c == start:
            src.send(good)
        if c < n_stale:
            word_if = _beat(ctrl, stale[c * N : (c + 1) * N], last=False)
        else:
            word_if = src.step(1)
        rst = 1 if rst_from <= c < rst_until else 0
        r = sim_call(ctrl, axis_in_if=word_if, rst=rst)
        log.append({"updated": int(r.updated), "rst": rst, "regs": _regs(r)})

    ups = [c for c, s in enumerate(log) if s["updated"] and not s["rst"]]
    assert len(ups) == 1, (
        f"expected exactly one post-reset update, got {ups} -- the abandoned "
        "prefix joined up with the good frame"
    )
    got = log[ups[0] + ctrl.latency]["regs"]
    assert got == _want(CFG_B), (
        f"the frame after the reset decoded as something other than itself: "
        f"{got}"
    )
    print("test_reset_flushes_an_abandoned_frame passed")


if __name__ == "__main__":
    print(f"pdw_ctrl: {CTRL_N_BYTES} bytes, {ctrl.n_beats} beats of {N}, "
          f"latency {ctrl.latency}")
    test_defaults_at_reset()
    test_ready_is_always_high()
    test_exact_frame_applies_after_last_beat()
    test_latency_is_independent_of_registered_ready()
    test_back_to_back_frames_both_apply()
    test_oversized_frame_drops_padding()
    test_runt_frame_is_discarded()
    test_reset_holds_defaults()
    test_frame_applies_after_reset_release()
    test_reset_flushes_an_abandoned_frame()
    print("All pdw_ctrl tests passed")
