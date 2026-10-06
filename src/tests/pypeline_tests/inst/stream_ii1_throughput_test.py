# pyright: reportInvalidTypeForm=none
"""One word per cycle (II=1) through every elastic AUTO_PIPELINE stream block.

make_stream_auto_pipeline admits words against an in-flight credit count. A
credit is out for L+5 cycles (input reg, L core regs, output reg, the FIFO's
2-cycle push-to-valid, the registered ready), so it must allow L+5 words in
flight to accept one word per cycle. It once allowed only L+2 and ran at
(L+2)/(L+5) words per cycle. The elastic DSP factories all sit on top of it.

Checks, with an always-valid producer and an always-ready consumer:
- make_stream_auto_pipeline(latency=L): inputs are accepted on consecutive
  cycles, results come out on consecutive cycles, the first result L+4 cycles
  after the first accept;
- the returned function's .auto_pipeline.latency is L and .max_in_flight L+5;
- a stalled consumer: exactly .max_in_flight words are admitted, and all of
  them come out in order afterwards (the FIFO holds every admitted word);
- the elastic make_fir / make_fir_decim / make_fir_interp / make_dc_block /
  make_moving_avg / make_magnitude: input and output at their nominal rates.
"""

import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "..",
        "..",
        "include",
        "pypeline",
    ),
)
from pypeline import hw_func, uint8_t, sim_call, sim_reset

from stream.stream_auto_pipeline import make_stream_auto_pipeline
from fixed_point import make_fixed_t
from dsp.fir import make_fir
from dsp.fir_decim import make_fir_decim
from dsp.fir_interp import make_fir_interp
from dsp.dc_block import make_dc_block
from dsp.moving_avg import make_moving_avg
from dsp.magnitude import make_magnitude


@hw_func
def plus_three(x: uint8_t) -> uint8_t:
    return x + 3


LATENCIES = (0, 1, 2, 3, 4, 5, 8)
SAPS = {L: make_stream_auto_pipeline(plus_three, latency=L)[0] for L in LATENCIES}

N_WORDS = 40


def _sap_cycle(sap, data, valid, ready):
    return sim_call(
        sap,
        sap.in_fwd_t(stream=sap.in_intrf.stream_t(data=data, valid=valid)),
        sap.out_fb_t(ready=ready),
    )


def test_stream_auto_pipeline_sizing_metadata():
    for L, sap in SAPS.items():
        assert sap.auto_pipeline.latency == L, (L, sap.auto_pipeline.latency)
        assert sap.max_in_flight == L + 5, (L, sap.max_in_flight)
        assert type(sap.max_in_flight) is int
        assert not hasattr(sap, "latency")


def test_stream_auto_pipeline_one_word_per_cycle():
    for L, sap in SAPS.items():
        sim_reset()
        sent = 0
        accept_cycles, out_cycles, got = [], [], []
        for cycle in range(N_WORDS + L + 20):
            valid = 1 if sent < N_WORDS else 0
            r = _sap_cycle(sap, sent, valid, 1)
            if valid and int(r.stream_in_if.ready):
                accept_cycles.append(cycle)
                sent += 1
            if int(r.stream_out_if.stream.valid):
                out_cycles.append(cycle)
                got.append(int(r.stream_out_if.stream.data))
        first = accept_cycles[0]
        assert accept_cycles == list(range(first, first + N_WORDS)), (
            f"latency={L}: input not accepted every cycle: {accept_cycles}"
        )
        assert got == [(x + 3) & 0xFF for x in range(N_WORDS)], (L, got)
        assert out_cycles == list(range(first + L + 4, first + L + 4 + N_WORDS)), (
            f"latency={L}: results not back to back from cycle {first + L + 4}: "
            f"{out_cycles}"
        )


def test_stream_auto_pipeline_stall_admits_round_trip():
    stall = 40
    for L, sap in SAPS.items():
        sim_reset()
        sent = 0
        got = []
        for cycle in range(stall + N_WORDS + L + 20):
            ready = 1 if cycle >= stall else 0
            valid = 1 if sent < N_WORDS else 0
            r = _sap_cycle(sap, sent, valid, ready)
            if valid and int(r.stream_in_if.ready):
                sent += 1
            if int(r.stream_out_if.stream.valid) and ready:
                got.append(int(r.stream_out_if.stream.data))
            if cycle == stall - 1:
                assert sent == L + 5 == sap.max_in_flight, (
                    f"latency={L}: a stalled consumer should admit exactly "
                    f"max_in_flight={sap.max_in_flight} words, admitted {sent}"
                )
                assert not got
        # Every admitted word was held (none dropped by a full FIFO)
        assert got == [(x + 3) & 0xFF for x in range(N_WORDS)], (L, got)


# Elastic DSP factories, each at two fixed core latencies
data_t = make_fixed_t(1, 7)
coeff_t = make_fixed_t(2, 6)
TAPS = [0.125, 0.375, 0.375, 0.125]


def _dsp_blocks():
    for L in (0, 2):
        yield f"make_fir L={L}", make_fir(TAPS, coeff_t, data_t, latency=L)[0], 1, 1
        for d in (1, 2, 3):
            block = make_fir_decim(TAPS, coeff_t, d, data_t, latency=L)[0]
            yield f"make_fir_decim D={d} L={L}", block, 1, d
        for i in (2, 4):
            block = make_fir_interp(TAPS, coeff_t, i, data_t, latency=L)[0]
            yield f"make_fir_interp I={i} L={L}", block, i, 1
        yield f"make_dc_block L={L}", make_dc_block(data_t, k=5, latency=L)[0], 1, 1
        yield f"make_moving_avg L={L}", make_moving_avg(data_t, 8, latency=L)[0], 1, 1
        yield f"make_magnitude L={L}", make_magnitude(data_t, latency=L)[0], 1, 1


def _sample(block, n):
    v = (n * 37) % 200 - 100
    if hasattr(block, "complex_t"):
        return block.complex_t(i=block.data_t(val=v), q=block.data_t(val=-v))
    return block.data_t(val=v)


def test_elastic_dsp_blocks_full_rate():
    """in_every: cycles between accepted inputs (fir_interp emits `interp`
    beats per input); out_every: cycles between results (fir_decim emits one
    per `decim` inputs)."""
    for name, block, in_every, out_every in _dsp_blocks():
        sim_reset()
        n_in = 24
        sent = 0
        accept_cycles, out_cycles = [], []
        for cycle in range(n_in * in_every + 40):
            valid = 1 if sent < n_in else 0
            r = sim_call(
                block,
                block.in_fwd_t(
                    stream=block.in_intrf.stream_t(data=_sample(block, sent), valid=valid)
                ),
                block.out_fb_t(ready=1),
            )
            if valid and int(r.stream_in_if.ready):
                accept_cycles.append(cycle)
                sent += 1
            if int(r.stream_out_if.stream.valid):
                out_cycles.append(cycle)
        assert sent == n_in, f"{name}: only {sent}/{n_in} inputs accepted"
        first = accept_cycles[0]
        assert accept_cycles == list(range(first, first + n_in * in_every, in_every)), (
            f"{name}: inputs not accepted every {in_every} cycle(s): {accept_cycles}"
        )
        n_out = n_in * in_every // out_every
        assert len(out_cycles) == n_out, f"{name}: {len(out_cycles)}/{n_out} results"
        o = out_cycles[0]
        assert out_cycles == list(range(o, o + n_out * out_every, out_every)), (
            f"{name}: results not every {out_every} cycle(s): {out_cycles}"
        )


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
