# pyright: reportInvalidTypeForm=none
"""stream/stream_perf_probe.py end to end, under the real native simulator
(`pypelinec stream_perf_probe_test.py --sim --comb --run 200`) and through
VHDL elaboration (`--comb` synth entry): the probes must vanish from the
hardware and, in sim, report the right numbers.

Two MAINs instantiate the same probed producer -> make_probed_stream_fifo ->
consumer chain. Each consumer accepts one word every PERIOD cycles (3 on the
left, 2 on the right), so its FIFO fills and backpressures the producer.
Every handshake is closed through Feedback[T] in the chain body, so it runs
in a convergence loop whose non-final passes must not reach the probes.
The @final(sim=True) hook checks:

- tap names are qualified by MAIN through MAIN_LABELS (`left/`, `right/`),
  with the shared hw_funcs' taps kept apart per instance;
- every tap counted every cycle exactly once (stream_bottleneck.check_taps);
- the consumer's service period is its PERIOD, the full FIFO's high water is
  its capacity and its transfer accounting conserves;
- stream_bottleneck walks past the FIFO (which only relays the stall) and
  names the consumer as the bottleneck on both sides.
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

from typing import NamedTuple

from pypeline import MAIN, Feedback, Reg, final, hw_func, struct, uint1_t, uint8_t

from stream import stream_bottleneck
from stream import stream_perf_probe as probe

FIFO_DEPTH = 4
fifo, fifo_t = probe.make_probed_stream_fifo(uint8_t, FIFO_DEPTH, "fifo")
intrf = fifo.stream_intrf

CONSUMER_STATE_NAMES = ("READY", "COOLDOWN")

probe.MAIN_LABELS.update({"left_main": "left", "right_main": "right"})
probe.REGISTRY.enable(["all"])

BLOCKS = {
    "fifo": stream_bottleneck.block_spec("fifo.in", "fifo.out", ("consumer",), None, "FIFO"),
    "consumer": stream_bottleneck.block_spec(
        "consumer.in", None, (), "consumer.fsm", "1-in-PERIOD consumer"
    ),
}
PERIODS = {"left": 3, "right": 2}


@hw_func
def producer(in_ready: uint1_t) -> intrf.stream_t:
    """Always offers the next word."""
    sent: Reg[uint8_t]
    o: intrf.stream_t
    o.data = sent
    o.valid = 1
    if in_ready:
        sent = sent + 1
    probe.hs("producer.out", o.valid, in_ready)
    return o


@struct
class consumer_t(NamedTuple):
    ready: uint1_t
    taken: uint8_t


@hw_func
def consumer(word: intrf.stream_t, period: uint8_t) -> consumer_t:
    """Ready one cycle in `period`: after each accepted word, counts down
    period-1 cycles before it is ready again."""
    cooldown: Reg[uint8_t]
    taken: Reg[uint8_t]
    probe.state("consumer.fsm", cooldown != 0, CONSUMER_STATE_NAMES)
    o: consumer_t
    o.ready = cooldown == 0
    o.taken = taken
    if word.valid & o.ready:
        cooldown = period - 1
        taken = taken + 1
    elif cooldown != 0:
        cooldown = cooldown - 1
    probe.hs("consumer.in", word.valid, o.ready)
    return o


def _chain(period):
    @hw_func
    def chain() -> uint8_t:
        in_ready: Feedback[uint1_t]
        out_ready: Feedback[uint1_t]
        word = producer(in_ready)
        f = fifo(intrf.fwd_t(stream=word), intrf.fb_t(ready=out_ready))
        c = consumer(f.out_stream_if.stream, period)
        in_ready = f.in_stream_if.ready
        out_ready = c.ready
        return c.taken

    return chain


left_chain = _chain(PERIODS["left"])
right_chain = _chain(PERIODS["right"])


@MAIN
def left_main() -> uint8_t:
    return left_chain()


@MAIN
def right_main() -> uint8_t:
    return right_chain()


@final(sim=True)
def check_taps():
    taps = probe.REGISTRY.snapshot()
    expected = {
        f"{side}/{name}"
        for side in PERIODS
        for name in ("producer.out", "fifo.in", "fifo.out", "fifo.occupancy",
                     "consumer.in", "consumer.fsm")
    }
    assert set(taps) == expected, f"tap names {sorted(taps)}"
    check = stream_bottleneck.check_taps(taps)
    assert check["consistent"], f"a probe counted a cycle more than once: {check}"
    cycles = check["cycles"]
    assert cycles >= 100, cycles

    phase = {"name": "run", "packet_bytes": 1, "num_packets": 1, "taps": taps}
    stream_bottleneck.analyze_phase(phase, BLOCKS, list(PERIODS), bus_bytes=1)
    assert stream_bottleneck.buffer_tap_errors(
        phase, {f"{side}/fifo": fifo.capacity_beats for side in PERIODS},
        taps_required=True, settled=False) == []
    for side, period in PERIODS.items():
        consumer_in = taps[f"{side}/consumer.in"]
        # Offered continuously once the FIFO has data: one beat per `period`
        # cycles, give or take a partial cooldown at the end of the run.
        assert abs(consumer_in["service_period_cycles"] - period) < 0.1, (side, consumer_in)
        occupancy = taps[f"{side}/fifo.occupancy"]
        assert occupancy["high_water_beats"] == fifo.capacity_beats, (side, occupancy)
        assert taps[f"{side}/fifo.in"]["stall_frac"] > 0.3, (side, taps[f"{side}/fifo.in"])
        fsm = taps[f"{side}/consumer.fsm"]
        assert fsm["dominant"] == ("COOLDOWN" if period > 2 else fsm["dominant"]), fsm
        verdict = phase["bottleneck"][side]
        assert verdict["block"] == "consumer", (side, verdict)
        assert phase["blocks"][side]["fifo"]["relay_limited"], phase["blocks"][side]["fifo"]
    print(f"stream_perf_probe_test: PASS ({cycles} cycles)")
