# pyright: reportInvalidTypeForm=none
"""A complete stream performance testbench under the real native simulator
(`pypelinec stream_perf_tb_test.py --sim --comb --run all`) -- the shape
pypeline_stream_perf_guide.md documents:

- @sim_input presents the next AXIS word (ConvergedAxisSimSource.drive) and
  the consumer's ready pattern (one beat accepted every other cycle) through
  module-level Input[T] wires, so the top also elaborates to HDL;
- @sim_output commits the converged input handshake, measures both
  boundaries (PhaseRunner/StreamMeter), checks every packet against a
  Scoreboard through a ConvergedAxisSimSink, and calls sim_finish() once the
  phase plan is done;
- the DUT is make_probed_stream_fifo -> make_probed_skid_buffer, so the
  internal taps land in each phase too;
- @final(sim=True) checks the recorded results: every packet checked, exact
  byte accounting, a 2 B/cycle sustained rate (a 4-byte bus drained every
  other cycle), consistent taps and the bottleneck verdict.
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

from pypeline import (
    MAIN, Feedback, Input, final, sim_finish, sim_input, sim_output, sim_print, uint1_t,
)

from axi.axis import make_axis_interface
from axi.axis_sim import ConvergedAxisSimSink, ConvergedAxisSimSource, Scoreboard
from stream import stream_bottleneck
from stream import stream_perf_probe as probe
from stream.stream_perf import PerfRecorder, PhaseBarrier, PhaseRunner, packet_size_phases

BUS = 4
axis_intrf = make_axis_interface(BUS)
frag_t = axis_intrf.stream_t.typeof("data")

# The DUT: a probed FIFO feeding a probed register slice.
fifo, fifo_t = probe.make_probed_stream_fifo(frag_t, 8, "fifo")
out_slice, out_slice_t = probe.make_probed_skid_buffer(axis_intrf, "out_slice")

BLOCKS = {
    "fifo": stream_bottleneck.block_spec("fifo.in", "fifo.out", ("out_slice",)),
    "out_slice": stream_bottleneck.block_spec("out_slice.in", "out_slice.out"),
}

probe.MAIN_LABELS.update({"perf_tb": "dut"})
probe.REGISTRY.enable(["all"])

PACKETS = 4
phases = packet_size_phases([32, 64], PACKETS, peak_bytes=10, peak_packets=2)
recorder = PerfRecorder("", {"bus_bytes": BUS})  # a path writes JSON per phase
scoreboard = Scoreboard()
src = ConvergedAxisSimSource(axis_intrf, BUS)
snk = ConvergedAxisSimSink(axis_intrf, BUS, scoreboard=scoreboard)


def frame_builder(length, rng):
    """(input frame, expected output frame, scoreboard metadata)."""
    payload = bytes(rng.randrange(256) for _ in range(length))
    return payload, payload, {}


runner = PhaseRunner(
    "dut", phases, PhaseBarrier(["dut"]), recorder, src, snk, scoreboard,
    frame_builder, bus_bytes=BUS, seed=1, stall_timeout_cycles=200,
    taps=probe.REGISTRY,
)
_cycle = [0]


def _nbytes(stream):
    return sum(1 for i in range(BUS) if stream.data.frag.keep[i]) if stream.valid else 0


# @sim_input values reach the design through module-level Input[T] wires, so
# the same top also elaborates to HDL (where they become top-level ports) --
# needed for a pipelined (non---comb) run, which synthesizes it first.
tb_in_word: Input[axis_intrf.stream_t]
tb_out_ready: Input[uint1_t]


@sim_input
def drive_in() -> axis_intrf.stream_t:
    runner.prepare_input()
    return src.drive().stream


@sim_input
def drive_out_ready() -> uint1_t:
    _cycle[0] += 1
    return _cycle[0] % 2


@sim_output
def measure(in_stream, in_ready, out_stream, out_ready):
    runner.note_in(in_stream.valid, in_ready, _nbytes(in_stream), in_stream.data.eod[0])
    src.commit(in_ready)
    moved = out_stream.valid and out_ready
    runner.note_out(moved, _nbytes(out_stream) if moved else 0, out_stream.data.eod[0])
    snk.step(axis_intrf.fwd_t(out_stream), out_ready)
    result = snk.check_nowait()
    if result is not None:
        runner.note_checked(result["passed"], f"packet {result.get('idx')} mismatch")
    for line in runner.drain_log():
        sim_print(line)
    runner.tick()
    if runner.done:
        sim_finish()


@MAIN
def perf_tb() -> axis_intrf.fwd_t:
    slice_ready: Feedback[uint1_t]
    tb_in_word = drive_in()
    tb_out_ready = drive_out_ready()
    f = fifo(axis_intrf.fwd_t(stream=tb_in_word), axis_intrf.fb_t(ready=slice_ready))
    s = out_slice(f.out_stream_if, axis_intrf.fb_t(ready=tb_out_ready))
    slice_ready = s.stream_in_if.ready
    measure(tb_in_word, f.in_stream_if.ready, s.stream_out_if.stream, tb_out_ready)
    return s.stream_out_if


@final(sim=True)
def check_results():
    raw = recorder.as_dict()
    checks = raw["checks"]
    assert runner.done, "phase plan did not finish"
    assert checks["functional_pass"], checks["errors"]
    assert checks["packets_checked"] == sum(p["num_packets"] for p in phases), checks
    for phase in raw["phases"]:
        res = phase["dut"]
        planned = phase["packet_bytes"] * phase["num_packets"]
        assert res["in_payload_bytes"] == res["out_payload_bytes"] == planned, res
        if phase["packet_bytes"] % BUS == 0:
            # Back-to-back full beats, drained one beat every other cycle.
            assert abs(res["sustained_bytes_per_cycle"] - BUS / 2) < 0.05, (phase["name"], res)
        stream_bottleneck.analyze_phase(phase, BLOCKS, ["dut"], bus_bytes=BUS)
        assert phase["taps_check"]["consistent"], phase["taps_check"]
        assert stream_bottleneck.buffer_tap_errors(
            phase, {"dut/fifo": fifo.capacity_beats, "dut/out_slice": out_slice.capacity_beats},
            taps_required=True) == []
        assert phase["taps"]["dut/fifo.in"]["bytes"] == planned
        assert phase["bottleneck"]["dut"]["block"] == "out_slice", phase["bottleneck"]
        assert phase["blocks"]["dut"]["out_slice"]["relay_limited"]
    print(f"stream_perf_tb_test: PASS ({runner.meter.cycle} cycles, "
          f"{checks['packets_checked']} packets)")
