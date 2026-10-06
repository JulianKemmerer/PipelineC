# pyright: reportInvalidTypeForm=none
"""stream/stream_perf*.py + stream/stream_bottleneck.py + the converged AXIS
sim source/sink: the metric definitions every measured design is compared
on, checked against hand-worked synthetic traces, plus a sim_call run of a
probed FIFO driven by axi.axis_sim.ConvergedAxisSimSource.

The end-to-end pypelinec --sim run (probes under real MAIN labels, Feedback
re-execution, VHDL elaboration) is stream_perf_probe_test.py.
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "..", "..", "include", "pypeline",
    ),
)

from pypeline import sim_call, sim_reset

from axi.axis import make_axis_interface
from axi.axis_sim import ConvergedAxisSimSink, ConvergedAxisSimSource, Scoreboard
from stream import stream_bottleneck as sb
from stream import stream_perf_probe as probe
from stream.stream_perf import (
    ArbTap,
    BufferTap,
    PerfRecorder,
    PhaseBarrier,
    PhaseRunner,
    StateTap,
    StreamMeter,
    TapRegistry,
    packet_size_phases,
    stream_fifo_capacity_beats,
)
from stream.stream_perf_report import (
    derive_throughput,
    markdown_boundary_table,
    splice_markers,
    summarize,
)

BUS = 16


def _close(got, want, tol=1e-9):
    if isinstance(want, float):
        return isinstance(got, (int, float)) and abs(got - want) < tol
    return got == want


def _check(checks):
    bad = [f"{n}: expected {w!r} got {g!r}" for n, g, w in checks if not _close(g, w)]
    assert not bad, "\n".join(bad)


# --------------------------------------------------------------------------
# StreamMeter: boundary metrics
# --------------------------------------------------------------------------
def test_meter_hand_worked_trace():
    phase = {"name": "t", "packet_bytes": 32, "num_packets": 2}
    m = StreamMeter("t", BUS)
    # in: pkt0 beats at cycles 0,1; a stall at 2 (valid but not ready); pkt1
    # beats at 3,4. out: pkt0 at 10,11; pkt1 at 20,21.
    in_sched = {0: (1, 1, BUS, 0), 1: (1, 1, BUS, 1), 2: (1, 0, BUS, 0),
                3: (1, 1, BUS, 0), 4: (1, 1, BUS, 1)}
    out_sched = {10: (1, BUS, 0), 11: (1, BUS, 1), 20: (1, BUS, 0), 21: (1, BUS, 1)}
    for cycle in range(22):
        if cycle in in_sched:
            m.note_in(*in_sched[cycle])
            m.note_in(*in_sched[cycle])  # idempotence: must not double-count
        if cycle in out_sched:
            m.note_out(*out_sched[cycle])
            m.note_out(*out_sched[cycle])
        m.tick()
    res = m.phase_result(phase)
    lat = res["latency_cycles"]
    _check([
        ("window_cycles", res["window_cycles"], 22),
        ("in_beats", res["in_beats"], 4),
        ("out_beats", res["out_beats"], 4),
        ("in_stall_cycles", res["in_stall_cycles"], 1),
        ("goodput_bytes", res["goodput_bytes"], 64),
        ("bytes_per_cycle", res["bytes_per_cycle"], 64 / 22),
        ("in_duty", res["in_duty"], 4 / 22),
        ("out_duty", res["out_duty"], 4 / 22),
        ("packets_out", res["packets_out"], 2),
        ("cold_head", lat["cold_head"], 10),
        ("head_max", lat["head_max"], 17),
        ("total_min", lat["total_min"], 11),
        ("total_max", lat["total_max"], 18),
        # too few beats for a trimmed steady-state window to mean anything
        ("steady_in", res["steady_in_bytes_per_cycle"], None),
        ("steady_out", res["steady_out_bytes_per_cycle"], None),
        ("beats_per_packet", res["beats_per_packet"], 2.0),
        ("packet_period_cycles", res["packet_period_cycles"], 10.0),
        ("sustained_bytes_per_cycle", res["sustained_bytes_per_cycle"], 32 / 10.0),
    ])


def test_meter_steady_rates():
    # 40 back-to-back beats, one per cycle, is exactly 16 B/cycle both sides.
    m = StreamMeter("t2", BUS)
    for cycle in range(40):
        m.note_in(1, 1, BUS, 1 if cycle == 39 else 0)
        m.note_out(1, BUS, 1 if cycle == 39 else 0)
        m.tick()
    res = m.phase_result({"name": "p", "packet_bytes": 640, "num_packets": 1})
    _check([("steady_in", res["steady_in_bytes_per_cycle"], 16.0),
            ("steady_out", res["steady_out_bytes_per_cycle"], 16.0)])
    # Accepting one beat every 4th cycle sustains 4 B/cycle on the input side
    # even while the output drains in a back-to-back burst (store-and-forward):
    # the two steady numbers must not be conflated.
    m3 = StreamMeter("t3", BUS)
    for cycle in range(120):
        m3.note_in(1, 1 if cycle % 4 == 0 else 0, BUS, 1 if cycle == 116 else 0)
        if cycle >= 90:
            m3.note_out(1, BUS, 1 if cycle == 119 else 0)
        m3.tick()
    res3 = m3.phase_result({"name": "p", "packet_bytes": 480, "num_packets": 1})
    assert abs((res3["steady_in_bytes_per_cycle"] or 0) - 4.0) < 0.2, res3
    _check([("steady_out burst", res3["steady_out_bytes_per_cycle"], 16.0)])


# --------------------------------------------------------------------------
# Taps
# --------------------------------------------------------------------------
def test_handshake_tap():
    reg = TapRegistry(["all"])
    hs = reg.tap("a/mac.data_in")
    # Offered every cycle, accepted 1 cycle in 6 (a multi-cycle block).
    for cycle in range(60):
        hs.note(1, 1 if cycle % 6 == 0 else 0, BUS if cycle % 6 == 0 else None)
    snap = hs.snapshot()
    _check([
        ("cycles", snap["cycles"], 60), ("xfer", snap["xfer_cycles"], 10),
        ("stall", snap["stall_cycles"], 50), ("starved", snap["starved_cycles"], 0),
        ("idle", snap["idle_cycles"], 0), ("offered", snap["offered_cycles"], 60),
        ("service_period", snap["service_period_cycles"], 6.0),
        ("accept_rate", snap["accept_rate"], 1 / 6),
        ("bytes_per_beat", snap["bytes_per_beat"], 16.0),
        ("bytes_per_cycle", snap["bytes_per_cycle"], 160 / 60),
        ("stall_frac", snap["stall_frac"], 50 / 60),
    ])
    # A consumer that is never offered work reads as starved, not as slow.
    starved = reg.tap("a/tail.in")
    for _ in range(40):
        starved.note(0, 1)
    s = starved.snapshot()
    _check([("starve_frac", s["starve_frac"], 1.0), ("stall_frac", s["stall_frac"], 0.0),
            ("service_period", s["service_period_cycles"], None)])


def test_epoch_keeps_last_converged_sample():
    # A body carrying Feedback[T] re-executes until it converges: three
    # firings per cycle count as ONE cycle, recording the LAST sample.
    fb = TapRegistry(["all"]).tap("a/x.in")
    for cycle in range(10):
        fb.sample(cycle + 1, (1, 0, None))
        fb.sample(cycle + 1, (1, 0, None))
        fb.sample(cycle + 1, (1, 1, BUS))
    fb.flush()
    s = fb.snapshot()
    _check([("cycles", s["cycles"], 10), ("xfer", s["xfer_cycles"], 10),
            ("stall", s["stall_cycles"], 0),
            ("first_transfer_cycle", s["first_transfer_cycle"], 0),
            ("last_transfer_cycle", s["last_transfer_cycle"], 9)])


def test_buffer_tap():
    bt = BufferTap("a/fifo.occupancy")
    bt.sample(1, (1, 0, 3))
    bt.sample(1, (0, 0, 3))
    bt.sample(1, (1, 0, 3))  # last converged firing wins
    bt.sample(2, (1, 1, 3))
    bt.flush()
    assert bt.snapshot()["end_occupancy"] == 1 and bt.accepted == 2 and bt.retired == 1
    bt.reset()
    bt.note(0, 1, 3)
    assert bt.start_occupancy == 1 and bt.occupancy == 0, "phase reset lost resident data"
    try:
        bt.note(0, 1, 3)
    except ValueError:
        pass
    else:
        raise AssertionError("buffer tap missed an underflow")
    assert stream_fifo_capacity_beats(2) == 3
    assert stream_fifo_capacity_beats(64) == 65
    assert stream_fifo_capacity_beats(100) == 129


def test_state_and_arb_taps():
    reg = TapRegistry(["all"])
    st = reg.tap("a/mac.fsm", StateTap)
    names = ("IDLE", "START", "WAIT", "FINISH")
    for cycle in range(60):
        st.note(1 if cycle % 6 == 0 else 2, names)
    s = st.snapshot()
    assert s["dominant"] == "WAIT", s
    _check([("WAIT frac", s["states"]["WAIT"]["frac"], 50 / 60)])

    # An arbiter that alternates unconditionally wastes every other slot when
    # only one side has work.
    arb = reg.tap("shared/pipe.arb", ArbTap, ("a", "b"))
    for cycle in range(40):
        arb.note(0 if cycle % 2 == 0 else 1, (1, 0), 1)
    a = arb.snapshot()["per_requester"]["a"]
    _check([("xfer", a["xfer_cycles"], 20), ("wasted", a["wasted_slot_cycles"], 20),
            ("wasted_frac", a["wasted_slot_frac"], 0.5), ("contention", a["contention_frac"], 0.0)])
    full = reg.tap("shared/pipe.arb_full", ArbTap, ("a", "b"))
    for cycle in range(40):
        # both always want it; the resource is ready on half the cycles
        full.note(0 if cycle % 2 == 0 else 1, (1, 1), 1 if cycle % 4 < 2 else 0)
    f = full.snapshot()["per_requester"]["a"]
    parts = (f["xfer_cycles"], f["blocked_cycles"], f["contention_cycles"], f["wasted_slot_cycles"])
    assert parts == (10, 10, 20, 0) and sum(parts) == f["req_cycles"], f


def test_registry_enablement():
    narrow = TapRegistry(["mac"])
    assert narrow.tap("a/mac.data_in").snapshot() is not None, "bare-name prefix"
    assert narrow.tap("a/fmt.in").snapshot() is None, "unmatched -> NullTap"
    by_label = TapRegistry(["b/"])
    assert by_label.tap("b/mac.data_in").snapshot() is not None, "label prefix"
    off = TapRegistry([])
    assert not off.any_enabled() and off.tap("a/mac.data_in").snapshot() is None
    late = TapRegistry()
    assert late.tap("a/mac.data_in").snapshot() is None
    late.enable(["all"])  # enabling later must drop cached NullTaps
    assert late.tap("a/mac.data_in").snapshot() is not None
    assert late.active_names() == ["a/mac.data_in"]


def test_packet_size_phases():
    phases = packet_size_phases([16, 64], 4, peak_bytes=1920, peak_packets=2)
    assert [p["name"] for p in phases] == ["b2b-16", "b2b-64", "peak-1920"]
    assert phases[-1]["num_packets"] == 2
    try:
        packet_size_phases([4096], 2, max_packet_bytes=2032)
    except ValueError:
        pass
    else:
        raise AssertionError("an over-limit packet size must raise")


# --------------------------------------------------------------------------
# Bottleneck attribution
# --------------------------------------------------------------------------
# A neutral 4-block graph shaped like a cipher+MAC datapath: fmt feeds the
# framer, which feeds a multi-cycle mac; split forks into fmt and framer.
BLOCKS = {
    "fmt": sb.block_spec("fmt.in", "fmt.out", ("framer", "tail"), "fmt.fsm", "formatter"),
    "framer": sb.block_spec("framer.in", "framer.out", ("mac",), "framer.fsm", "framer"),
    "mac": sb.block_spec("mac.data_in", "mac.tag_out", (), "mac.fsm", "multi-cycle MAC"),
    "tail": sb.block_spec("tail.in", "tail.out", (), "tail.fsm", "tail merge"),
    "split": sb.block_spec("split.in", "split.out", ("fmt", "framer"), None, "fork"),
}
CYC = 600


def _hs(xfer, stall, starved=0, bpb=16.0, **extra):
    d = {"kind": "handshake", "cycles": CYC, "xfer_cycles": xfer, "stall_cycles": stall,
         "starved_cycles": starved, "idle_cycles": 0,
         "accept_rate": xfer / (xfer + stall) if xfer + stall else None,
         "service_period_cycles": (xfer + stall) / xfer if xfer else None,
         "bytes_per_beat": bpb, "bytes_per_cycle": xfer * bpb / CYC,
         "stall_frac": stall / CYC, "starve_frac": starved / CYC}
    d.update(extra)
    return d


def _mac_limited_taps():
    # mac is the limiter: its input stalls hard and is never starved; fmt is
    # mostly starved; framer only RELAYS mac's stall (its output stalls harder).
    return {
        "a/fmt.in": _hs(100, 60, 440),
        "a/fmt.out": _hs(100, 300),
        "a/framer.in": _hs(100, 300, 200),
        "a/framer.out": _hs(100, 500),
        "a/mac.data_in": _hs(100, 500),
        "a/mac.tag_out": _hs(4, 0, 120),
        "a/mac.fsm": {"kind": "state", "cycles": CYC, "dominant": "WAIT",
                      "states": {"START": {"cycles": 100, "frac": 100 / CYC},
                                 "WAIT": {"cycles": 500, "frac": 500 / CYC}}},
    }


def test_rollup_and_verdict():
    phase = {"name": "b2b-1420", "packet_bytes": 1420, "num_packets": 4,
             "taps": _mac_limited_taps(), "a": {"sustained_bytes_per_cycle": 2.51}}
    sb.analyze_phase(phase, BLOCKS, ["a", "b"], bus_bytes=BUS)
    blocks = phase["blocks"]["a"]
    assert sorted(blocks) == ["fmt", "framer", "mac"]
    _check([("mac ceiling", blocks["mac"]["ceiling_bytes_per_cycle"], 16 / 6.0),
            ("fmt ceiling", blocks["fmt"]["ceiling_bytes_per_cycle"], 10.0)])
    assert blocks["fmt"]["relay_limited"] and not blocks["mac"]["relay_limited"]
    verdict = phase["bottleneck"]["a"]
    # framer has the joint-highest input stall but its own output stalls
    # harder still, so the walk must land on mac.
    assert verdict["block"] == "mac" and verdict["dominant_state"] == "WAIT", verdict
    assert "mac" in verdict["evidence"] and "WAIT" in verdict["evidence"]
    assert phase["taps_check"] == {"cycles": CYC, "consistent": True}
    assert "b" not in phase["blocks"], "a label with no taps gets no rollup"

    # A fork is followed toward the sink that is actually stalling.
    fork = dict(_mac_limited_taps())
    fork["a/split.in"] = _hs(100, 520)
    fork["a/split.out"] = _hs(100, 520)
    assert sb.find_bottleneck(sb.block_rollup(fork, "a", BLOCKS, BUS), BLOCKS)["block"] == "mac"

    # A relay chain with nothing downstream must not loop forever.
    lonely = {"a/tail.in": _hs(1, 9)}
    assert sb.find_bottleneck(sb.block_rollup(lonely, "a", BLOCKS, BUS), BLOCKS)["block"] == "tail"

    # A label that never streamed gets no verdict; no taps is a no-op.
    idle = {"name": "x", "packet_bytes": 64, "num_packets": 2,
            "taps": {"b/mac.data_in": _hs(0, 0)}}
    sb.analyze_phase(idle, BLOCKS, ["a", "b"], BUS)
    assert "blocks" not in idle and "bottleneck" not in idle
    bare = {"name": "x", "packet_bytes": 64, "num_packets": 1}
    sb.analyze_phase(bare, BLOCKS, ["a"], BUS)
    assert "blocks" not in bare


def test_check_taps_spread():
    good = sb.check_taps({"a": {"cycles": 10}, "b": {"cycles": 10}})
    assert good == {"cycles": 10, "consistent": True}
    bad = sb.check_taps({"a": {"cycles": 10}, "b": {"cycles": 30}})
    assert not bad["consistent"] and bad["disagreeing_taps"] == ["b"]


def test_headline_and_best_ceiling():
    small = {"name": "b2b-256", "packet_bytes": 256, "blocks": {"a": {
        "fmt": {"ceiling_bytes_per_cycle": 14.2, "relay_limited": True},
        "mac": {"ceiling_bytes_per_cycle": 2.79, "relay_limited": False}}}}
    big = {"name": "peak-1920", "packet_bytes": 1920, "a": {"sustained_bytes_per_cycle": 2.532},
           "blocks": {"a": {
               "fmt": {"ceiling_bytes_per_cycle": 2.98, "relay_limited": True},
               "mac": {"ceiling_bytes_per_cycle": 2.70, "relay_limited": False}}}}
    c = sb.best_ceiling([small, big], "a", "fmt")
    assert (c[0], c[1]["packet_bytes"], c[2]) == (14.2, 256, False)
    m = sb.best_ceiling([small, big], "a", "mac")
    assert (m[0], m[1]["packet_bytes"], m[2]) == (2.70, 1920, True)
    head = "\n".join(sb.headline([small, big], ["a"], ("fmt", "mac"), {"fmt": "Fmt", "mac": "MAC"}))
    for needle in ("Fmt serves **≥14.20 B/cyc**", "MAC **2.70 B/cyc**", "at least **5.3x",
                   "94% of MAC's ceiling"):
        assert needle in head, (needle, head)


def test_markdown_and_csv():
    phase = {"name": "b2b-1420", "packet_bytes": 1420, "num_packets": 4,
             "taps": _mac_limited_taps(), "a": {"sustained_bytes_per_cycle": 2.51}}
    phase["taps"]["shared/pipe.arb"] = {
        "kind": "arb", "cycles": CYC, "labels": ["a", "b"],
        "per_requester": {
            "a": {"req_cycles": 40, "sel_cycles": 300, "xfer_cycles": 20,
                  "contention_cycles": 0, "wasted_slot_cycles": 20, "arb_loss_frac": 0.5,
                  "contention_frac": 0.0, "wasted_slot_frac": 0.5},
            # an old snapshot without blocked_cycles: derived from the identity
            # 100 - 10 - 30 - 20 = 40% not ready
            "b": {"req_cycles": 100, "sel_cycles": 300, "xfer_cycles": 10,
                  "contention_cycles": 30, "wasted_slot_cycles": 20, "arb_loss_frac": 0.5,
                  "contention_frac": 0.3, "wasted_slot_frac": 0.2}}}
    phase["taps"]["a/fifo.occupancy"] = {
        "kind": "buffer", "cycles": CYC, "capacity_beats": 65, "start_occupancy": 0,
        "end_occupancy": 0, "high_water_beats": 12, "accepted_beats": 100,
        "retired_beats": 100, "simultaneous_cycles": 80, "full_cycles": 0, "empty_cycles": 10}
    sb.analyze_phase(phase, BLOCKS, ["a"], BUS)
    extra = ["**Design-specific section**"]
    text = sb.markdown_blocks([phase], ["a"], BLOCKS, compare=("fmt", "mac"),
                              extra_sections=[extra], text={"label_header": "dir"})
    for needle in ("**Headline.**", "| phase | bytes | dir | block |", "≥10.000",
                   "| **mac** |", "| a | 40 | 20 |", "| b | 100 | 10 | 40% | 30% | 20% |",
                   "**Design-specific section**", "| b2b-1420 | a/fifo.occupancy | 65 | 12 |"):
        assert needle in text, (needle, text)
    # Section order: headline, blocks, verdicts, arbitration, extra, buffers.
    order = [text.index(n) for n in ("**Headline.**", "| fmt |", "**Bottleneck per phase**",
                                     "**Arbitration**", "**Design-specific", "**Buffers**")]
    assert order == sorted(order), order
    assert sb.markdown_blocks([{"name": "x", "packet_bytes": 1}], ["a"], BLOCKS) == \
        sb.DEFAULT_TEXT["no_taps"]

    blocks_csv = list(sb.block_rows("run", [phase]))
    assert len(blocks_csv) == 3 and all(len(r) == len(sb.BLOCK_CSV_COLUMNS) for r in blocks_csv)
    taps_csv = list(sb.tap_rows("run", [phase]))
    assert len(taps_csv) == len(phase["taps"])
    assert all(len(r) == len(sb.TAP_CSV_COLUMNS) for r in taps_csv)
    verdicts, total = sb.bottleneck_tally([phase], ["a"])
    assert verdicts == {"mac": ["a @ 1420 B"]} and total == 1


def test_buffer_tap_errors():
    good = {"kind": "buffer", "capacity_beats": 65, "start_occupancy": 0, "end_occupancy": 0,
            "high_water_beats": 9, "accepted_beats": 50, "retired_beats": 50}
    phase = {"name": "p", "taps": {"a/fifo.occupancy": good,
                                   "a/fifo.in": {"xfer_cycles": 50},
                                   "a/fifo.out": {"xfer_cycles": 50}}}
    assert sb.buffer_tap_errors(phase, {"a/fifo": 65}) == []
    assert sb.buffer_tap_errors(phase, {"a/other": 3}) == []
    assert sb.buffer_tap_errors(phase, {"a/other": 3}, taps_required=True)
    leaky = dict(good, end_occupancy=1)
    phase["taps"]["a/fifo.occupancy"] = leaky
    errors = sb.buffer_tap_errors(phase, {"a/fifo": 65})
    assert any("conservation" in e for e in errors) and any("left buffered" in e for e in errors)
    assert not any("left buffered" in e for e in sb.buffer_tap_errors(phase, {"a/fifo": 65}, settled=False))
    phase["taps"]["a/fifo.occupancy"] = good
    phase["taps"]["a/fifo.out"] = {"xfer_cycles": 49}
    assert any("out transfers" in e for e in sb.buffer_tap_errors(phase, {"a/fifo": 64}))


# --------------------------------------------------------------------------
# Boundary report
# --------------------------------------------------------------------------
def test_report():
    raw = {"phases": [{"name": "b2b-64", "packet_bytes": 64, "num_packets": 4, "a": {
        "bytes_per_cycle": 2.0, "sustained_bytes_per_cycle": 4.0, "steady_in_bytes_per_cycle": 8.0,
        "packet_period_cycles": 16.0, "in_stall_frac": 0.25,
        "latency_cycles": {"cold_head": 7, "total_med": 20}}}]}
    phases = derive_throughput(raw, 100.0, 50.0, BUS, ["a", "b"])
    a = phases[0]["a"]
    _check([("rate", a["throughput_bytes_per_cycle"], 4.0), ("line", a["line_rate_frac"], 0.25),
            ("gbps fmax", a["gbps_at_fmax"], 3.2), ("gbps target", a["gbps_at_target"], 1.6),
            ("window gbps", a["window_gbps_at_fmax"], 1.6),
            ("steady gbps", a["steady_in_gbps_at_fmax"], 6.4)])
    assert a["throughput_basis"].startswith("sustained")
    s = summarize(phases, ["a", "b"])
    assert s["peak_sustained_bytes_per_cycle_a"] == 4.0 and s["peak_bytes_per_cycle_b"] is None
    two = markdown_boundary_table(phases, ["a"], 100.0, 50.0)
    assert "Gb/s @fmax | Gb/s @target" in two[0] and "| 3.200 | 1.600 |" in two[2], two
    one = markdown_boundary_table(phases, ["a"], 50.0, 50.0)
    assert "Gb/s @50 MHz" in one[0] and "@target" not in one[0], one
    text = "head\n<!-- B -->\nold\n<!-- E -->\ntail"
    assert splice_markers(text, "<!-- B -->", "<!-- E -->", "new") == \
        "head\n<!-- B -->\n\nnew\n\n<!-- E -->\ntail"
    assert splice_markers("no markers", "<!-- B -->", "<!-- E -->", "x") is None


# --------------------------------------------------------------------------
# sim_call: a probed FIFO between the converged AXIS source and a slow,
# backpressuring converged sink, measured by a PhaseRunner.
# --------------------------------------------------------------------------
N = 4
axis_intrf = make_axis_interface(N)
FIFO_DEPTH = 4
pfifo, pfifo_t = probe.make_probed_stream_fifo(axis_intrf.stream_t.typeof("data"), FIFO_DEPTH, "fifo")


def test_probed_fifo_sim_call():
    assert pfifo.capacity_beats == 5 and pfifo.tap_name == "fifo"
    probe.REGISTRY.enable(["all"])
    sim_reset()
    scoreboard = Scoreboard()
    src = ConvergedAxisSimSource(axis_intrf, N)
    snk = ConvergedAxisSimSink(axis_intrf, N, scoreboard=scoreboard)
    phases = packet_size_phases([10, 16], 3)
    recorder = PerfRecorder("", {"test": True})
    runner = PhaseRunner(
        "a", phases, PhaseBarrier(["a"]), recorder, src, snk, scoreboard,
        lambda length, rng: (bytes(rng.randrange(256) for _ in range(length)),) * 2 + ({},),
        bus_bytes=N, seed=1, stall_timeout_cycles=200, taps=probe.REGISTRY)
    for cycle in range(400):
        runner.prepare_input()
        word = src.drive()
        out_ready = 1 if cycle % 3 == 0 else 0  # consumer takes 1 beat in 3
        r = sim_call(pfifo, word, pfifo.fb_t(ready=out_ready))
        in_ready = int(r.in_stream_if.ready)
        stream = word.stream
        runner.note_in(int(stream.valid), in_ready,
                       sum(stream.data.frag.keep) if stream.valid else 0, stream.data.eod[0])
        src.commit(in_ready)
        out = r.out_stream_if
        moved = int(out.stream.valid) and out_ready
        runner.note_out(moved, sum(out.stream.data.frag.keep) if moved else 0,
                        out.stream.data.eod[0] if moved else 0)
        snk.step(out, out_ready)
        result = snk.check_nowait()
        if result is not None:
            runner.note_checked(result["passed"], "payload mismatch")
        runner.tick()
        if runner.done:
            break
    assert runner.done, "phase plan did not finish"
    raw = recorder.as_dict()
    assert raw["checks"]["functional_pass"] and raw["checks"]["packets_checked"] == 6, raw["checks"]
    for phase in raw["phases"]:
        a = phase["a"]
        assert a["in_payload_bytes"] == a["out_payload_bytes"] == phase["packet_bytes"] * 3
        taps = phase["taps"]
        # Bare names under sim_call (no MAIN executing).
        assert set(taps) == {"fifo.in", "fifo.out", "fifo.occupancy"}, sorted(taps)
        assert sb.check_taps(taps)["consistent"], sb.check_taps(taps)
        # The consumer drains 1 beat per 3 cycles, so the full FIFO stalls its
        # producer and its output side serves at that rate.
        assert taps["fifo.out"]["xfer_cycles"] == taps["fifo.occupancy"]["retired_beats"]
        assert taps["fifo.in"]["xfer_cycles"] == taps["fifo.occupancy"]["accepted_beats"]
        assert taps["fifo.in"]["bytes"] == phase["packet_bytes"] * 3
        assert taps["fifo.occupancy"]["high_water_beats"] == pfifo.capacity_beats
        assert sb.buffer_tap_errors(phase, {"fifo": pfifo.capacity_beats}, True) == []
    assert snk.stalled_cycles > 0


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
