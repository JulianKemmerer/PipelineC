#!/usr/bin/env python3
# pyright: reportInvalidTypeForm=none
"""In-process unit tests for make_stream_auto_pipeline(func, *, latency=,
start_latency=, max_latency=) and the DSP factories that forward the same
keyword-only arguments to their single core AUTO_PIPELINE:
  - the arguments reach the eagerly constructed core AUTO_PIPELINE (which
    also sizes the FIFO), and bad combinations raise its errors;
  - .latency served per build mode: a sweep build's bootstrap reads
    start_latency, --comb-like builds read 0, latency=N reads N everywhere;
  - no arguments builds an unconstrained tag, and repeated constructions
    keep the same key and repr (re-elaboration);
  - plain native sim: a start_latency hint is cycle-identical to no hint,
    while a fixed latency=2 delays the first result by exactly 2 cycles;
  - every DSP factory and handshake forwards the arguments."""
import os
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(THIS_DIR, "..", "..", ".."))
sys.path.insert(0, os.path.join(THIS_DIR, "..", "..", "..", "..", "include", "pypeline"))

import pypeline
from pypeline import MAIN, hw_func, sim_call, sim_reset, uint8_t

from fixed_point import make_fixed_t
from stream.stream import make_stream_interface
from stream.stream_auto_pipeline import make_stream_auto_pipeline
from dsp.dc_block import make_dc_block
from dsp.fir import make_fir
from dsp.fir_decim import make_fir_decim
from dsp.fir_interp import make_fir_interp
from dsp.magnitude import make_magnitude
from dsp.moving_avg import make_moving_avg


@hw_func
def div_inv(x: uint8_t) -> uint8_t:
    return x / ~x


uint8_stream_intrf = make_stream_interface(uint8_t)
# Constructed at import, outside any pypelinec build (build mode None)
plain_sap, plain_sap_t = make_stream_auto_pipeline(div_inv)
hinted_sap, hinted_sap_t = make_stream_auto_pipeline(div_inv, start_latency=4, max_latency=6)
fixed_sap, fixed_sap_t = make_stream_auto_pipeline(div_inv, latency=2)


@MAIN(50.0)
def plain_sap_main(
    stream_in_if: uint8_stream_intrf.fwd_t, stream_out_if: uint8_stream_intrf.fb_t
) -> plain_sap_t:
    return plain_sap(stream_in_if, stream_out_if)


@MAIN(50.0)
def hinted_sap_main(
    stream_in_if: uint8_stream_intrf.fwd_t, stream_out_if: uint8_stream_intrf.fb_t
) -> hinted_sap_t:
    return hinted_sap(stream_in_if, stream_out_if)


@MAIN(50.0)
def fixed_sap_main(
    stream_in_if: uint8_stream_intrf.fwd_t, stream_out_if: uint8_stream_intrf.fb_t
) -> fixed_sap_t:
    return fixed_sap(stream_in_if, stream_out_if)


class _RecordAutoPipelines:
    """Records every AUTO_PIPELINE constructed inside the with-block."""

    def __enter__(self):
        self.made = []
        self._init = pypeline.AUTO_PIPELINE.__init__
        made, init = self.made, self._init

        def recording_init(ap, *args, **kwargs):
            init(ap, *args, **kwargs)
            made.append(ap)

        pypeline.AUTO_PIPELINE.__init__ = recording_init
        return self

    def __exit__(self, *exc):
        pypeline.AUTO_PIPELINE.__init__ = self._init
        return False


def _restore_auto_pipeline_state():
    pypeline.SET_AUTO_PIPELINE_BUILD_MODE(None)
    pypeline.SET_AUTO_PIPELINE_LATENCY_CACHE({})
    pypeline.CLEAR_AUTO_PIPELINE_LATENCY_READ_FLAG()


def _make_one(mode, **kwargs):
    """Construct one wrapper under build mode `mode`; returns its core AP and
    the .latency values served while sizing the FIFO."""
    pypeline.SET_AUTO_PIPELINE_BUILD_MODE(mode)
    pypeline.CLEAR_AUTO_PIPELINE_LATENCY_READ_FLAG()
    with _RecordAutoPipelines() as rec:
        make_stream_auto_pipeline(div_inv, **kwargs)
    assert len(rec.made) == 1, rec.made
    return rec.made[0], pypeline.AUTO_PIPELINE_SERVED_LATENCIES()


def test_forwarding_and_build_modes():
    try:
        for mode, hint_served in (("sweep", 4), ("fixed_only", 0)):
            ap, served = _make_one(mode, start_latency=4)
            assert (ap.fixed_latency, ap.start_latency, ap.max_latency) == (None, 4, None)
            assert ap.canonical_key.endswith("_start_latency_4"), ap.canonical_key
            assert served == {ap.canonical_key: {hint_served}}, (mode, served)

            ap, served = _make_one(mode, start_latency=1, max_latency=3)
            assert ap.canonical_key.endswith("_start_latency_1_max_latency_3")

            ap, served = _make_one(mode, latency=2)
            assert ap.canonical_key.endswith("_latency_2"), ap.canonical_key
            assert served == {ap.canonical_key: {2}}, (mode, served)

            # No arguments: an unconstrained tag (no AUTO_PIPELINE key suffix)
            ap, served = _make_one(mode)
            assert ap.latency_suffix() == "", ap.latency_suffix()
            assert not ap.canonical_key.endswith("_None"), ap.canonical_key
            assert served == {ap.canonical_key: {0}}, (mode, served)
    finally:
        _restore_auto_pipeline_state()


def test_stable_identity():
    try:
        first, _ = _make_one("sweep", start_latency=4)
        again, _ = _make_one("sweep", start_latency=4)
        plain, _ = _make_one("sweep")
        assert first.canonical_key == again.canonical_key
        assert repr(first) == repr(again) and "start_latency=4" in repr(first)
        assert first.canonical_key != plain.canonical_key
    finally:
        _restore_auto_pipeline_state()


def test_bad_arguments():
    bad = [
        ({"start_latency": 3, "max_latency": 2}, ValueError),
        ({"latency": 1, "start_latency": 1}, ValueError),
        ({"start_latency": -1}, ValueError),
        ({"start_latency": 1.5}, TypeError),
    ]
    for kwargs, exc in bad:
        try:
            make_stream_auto_pipeline(div_inv, **kwargs)
        except exc:
            pass
        else:
            raise AssertionError(f"make_stream_auto_pipeline accepted {kwargs}")
    try:
        make_stream_auto_pipeline(div_inv, 4)  # keyword-only: no MAX_IN_FLIGHT
    except TypeError:
        pass
    else:
        raise AssertionError("make_stream_auto_pipeline accepted a positional latency")


def _trace(main, inputs, cycles=40):
    """Per-cycle (in_ready, out_valid, out_data) with inputs presented in order
    and the consumer always ready."""
    sim_reset()
    idx, trace = 0, []
    for _ in range(cycles):
        valid = 1 if idx < len(inputs) else 0
        data = inputs[idx] if valid else 0
        r = sim_call(
            main,
            uint8_stream_intrf.fwd_t(stream=uint8_stream_intrf.stream_t(data=data, valid=valid)),
            uint8_stream_intrf.fb_t(ready=1),
        )
        ready = int(r.stream_in_if.ready)
        if valid and ready:
            idx += 1
        out_valid = int(r.stream_out_if.stream.valid)
        trace.append((ready, out_valid, int(r.stream_out_if.stream.data) if out_valid else 0))
    return trace


def test_native_sim_latency():
    inputs = [200, 240, 250, 128, 170, 220, 253]  # x / ~x nonzero
    expected = [int(sim_call(div_inv, x)) for x in inputs]
    plain = _trace(plain_sap_main, inputs)
    hinted = _trace(hinted_sap_main, inputs)
    fixed = _trace(fixed_sap_main, inputs)
    # A hint changes nothing in plain native sim: core latency stays 0
    assert hinted == plain, (plain, hinted)

    def outputs(trace):
        return [(cycle, data) for cycle, (_, valid, data) in enumerate(trace) if valid]

    assert [d for _, d in outputs(plain)] == expected, outputs(plain)
    assert [d for _, d in outputs(fixed)] == expected, outputs(fixed)
    assert all(expected), expected
    # The 2 fixed core registers delay the first result by exactly 2 cycles
    # (later spacing differs: the FIFO, and so in-flight capacity, grows to 4)
    assert outputs(fixed)[0][0] == outputs(plain)[0][0] + 2, (outputs(plain), outputs(fixed))


def test_dsp_factories_forward():
    data_t = make_fixed_t(1, 7)
    coeff_t = make_fixed_t(2, 6)
    taps = [0.25, 0.5, 0.5, 0.25]
    builders = {
        "make_fir": lambda h, **kw: make_fir(taps, coeff_t, data_t, handshake=h, **kw),
        "make_fir_decim": lambda h, **kw: make_fir_decim(taps, coeff_t, 2, data_t, handshake=h, **kw),
        "make_dc_block": lambda h, **kw: make_dc_block(data_t, k=5, handshake=h, **kw),
        "make_moving_avg": lambda h, **kw: make_moving_avg(data_t, 8, handshake=h, **kw),
        "make_magnitude": lambda h, **kw: make_magnitude(data_t, handshake=h, **kw),
    }
    cases = [(name, h, build) for name, build in builders.items() for h in ("elastic", "valid_only")]
    cases.append(("make_fir_interp", "elastic", lambda h, **kw: make_fir_interp(taps, coeff_t, 2, data_t, **kw)))
    try:
        pypeline.SET_AUTO_PIPELINE_BUILD_MODE("sweep")
        for name, handshake, build in cases:
            pypeline.CLEAR_AUTO_PIPELINE_LATENCY_READ_FLAG()
            with _RecordAutoPipelines() as rec:
                build(handshake, start_latency=2, max_latency=5)
            assert len(rec.made) == 1, (name, handshake, rec.made)
            ap = rec.made[0]
            assert (ap.start_latency, ap.max_latency) == (2, 5), (name, handshake)
            assert ap.latency == 2, (name, handshake, ap.latency)
            with _RecordAutoPipelines() as rec:
                build(handshake, latency=3)
            assert [ap.fixed_latency for ap in rec.made] == [3], (name, handshake)
    finally:
        _restore_auto_pipeline_state()


if __name__ == "__main__":
    test_forwarding_and_build_modes()
    test_stable_identity()
    test_bad_arguments()
    test_native_sim_latency()
    test_dsp_factories_forward()
    print("All make_stream_auto_pipeline latency argument tests passed.")
