# pyright: reportInvalidTypeForm=none
"""Testbench library for dsp/magnitude.py, dsp/dc_block.py, dsp/moving_avg.py
-- the non-FIR "detect and measure" blocks (see
examples/pypeline/dsp/pdw/README.md, Path A).

Same three-layer split as dsp/fir_tb.py (signal generators + exact integer
golden models + a @sim_input/@sim_output testbench factory), re-exporting
fir_tb's generators and golden_resize rather than duplicating them so a
testbench needs one import line.

@sim_input/@sim_output only exist in the native simulator, so a testbench
@MAIN built from make_block_tb runs under
`pypelinec <file> --sim --comb --run N` (never under GHDL/cocotb).
"""

import random
from types import SimpleNamespace

from pypeline import sim_input, sim_output, sim_print, uint1_t

from dsp.fir_tb import (  # noqa: F401 -- re-exported for one-line imports
    chirp,
    golden_resize,
    impulse,
    quantize_samples,
    sine,
    step,
    two_tone,
    white_noise,
)


# ─────────────────────────────────────────────
# Exact integer golden models
# ─────────────────────────────────────────────


def golden_magnitude(mag, iq_pairs):
    """Expected raw output ints for a dsp/magnitude.make_magnitude instance.

    iq_pairs: list of (i_raw, q_raw) raw input ints (pre-quantized).
    """
    shift = mag.acc_t.frac_bits - mag.out_t.frac_bits
    out_total = mag.out_t.int_bits + mag.out_t.frac_bits
    outs = []
    for i, q in iq_pairs:
        acc = i * i + q * q
        if mag.full_precision:
            outs.append(acc)
        else:
            outs.append(
                golden_resize(
                    acc, shift, out_total, mag.out_t.signed, mag.rounding, mag.overflow
                )
            )
    return outs


def golden_dc_block(dcb, samples_q):
    """Expected raw output ints for a dsp/dc_block.make_dc_block instance.

    Mirrors the hardware's leaky-integrator recursion exactly in Python's
    arbitrary-precision ints (>> on a possibly-negative int is floor, matching
    the hardware's arithmetic shift) -- assumes the mean estimate stays within
    its guarded hardware range, true for any well-behaved (non-pathological)
    stimulus.
    """
    k = dcb.k
    shift = dcb.diff_t.frac_bits - dcb.out_t.frac_bits
    out_total = dcb.out_t.int_bits + dcb.out_t.frac_bits
    mean = 0
    outs = []
    for x in samples_q:
        x_ext = x << k
        diff = x_ext - mean
        if dcb.full_precision:
            outs.append(diff)
        else:
            outs.append(
                golden_resize(
                    diff, shift, out_total, dcb.out_t.signed, dcb.rounding, dcb.overflow
                )
            )
        mean = mean + (diff >> k)
    return outs


def golden_moving_avg(ma, samples_q):
    """Expected raw output ints for a dsp/moving_avg.make_moving_avg instance.

    The window includes the current sample (dsp/fir_tb.golden_fir's
    convention). normalize=True's divide-by-n is purely a binary-point
    relabelling of the same raw sum (see moving_avg.py), so the golden model
    never actually divides -- it feeds the raw running sum straight into
    golden_resize with the shift computed from avg_t/out_t's frac_bits, same
    as the hardware.
    """
    n = ma.n
    shift = ma.avg_t.frac_bits - ma.out_t.frac_bits
    out_total = ma.out_t.int_bits + ma.out_t.frac_bits
    window = [0] * n
    outs = []
    for x in samples_q:
        window = [x] + window[:-1]
        s = sum(window)
        if ma.full_precision:
            outs.append(s)
        else:
            outs.append(
                golden_resize(
                    s, shift, out_total, ma.out_t.signed, ma.rounding, ma.overflow
                )
            )
    return outs


# ─────────────────────────────────────────────
# @sim_input / @sim_output testbench factory
# ─────────────────────────────────────────────


def make_block_tb(
    block,
    stimulus,
    expected,
    name="block",
    ready_pattern="always",
    seed=8439,
    deadline=None,
    in_value=None,
    out_value=None,
    idle_raw=0,
    on_done=None,
):
    """Build the sim-only driver/checker set for one dsp/magnitude|dc_block|
    moving_avg instance (any handshake="elastic"|"valid_only" mode).

    block:      the function returned by make_magnitude/make_dc_block/
                make_moving_avg (its metadata attributes are introspected).
    stimulus:   list of raw input items, one per accepted beat -- a raw int
                for dc_block/moving_avg, an (i_raw, q_raw) tuple for magnitude.
    expected:   golden raw output ints (golden_magnitude/golden_dc_block/
                golden_moving_avg).
    in_value:   raw item -> port data value; default `lambda raw:
                block.data_t(val=raw)` (magnitude passes a 2-line lambda
                building block.complex_t(i=..., q=...)).
    out_value:  observed data value -> raw int for comparison; default
                `lambda d: int(d.val)`.
    idle_raw:   the "no more data" raw item passed through in_value while
                draining (default 0; magnitude passes (0, 0)).
    on_done:    optional callable(state_dict) invoked once, right after the
                last expected output is matched -- for a behavioural check
                beyond exact golden matching (state["in_hist"]/["out_hist"]
                hold every accepted input / consumed output, raw ints).
    ready_pattern: "always" | "random" (seeded, ~70% ready) | callable(cycle)->bool.
                   Ignored for handshake="valid_only" blocks.
    deadline:   max cycles before the checker asserts non-completion (default:
                generous bound from the stimulus size). Run the sim for MORE
                than tb.min_cycles.

    Returns SimpleNamespace(drive_in, drive_ready, observe, state, expected,
    deadline, min_cycles).
    """
    n_in = len(stimulus)
    n_out = len(expected)
    if deadline is None:
        deadline = 4 * (n_in + n_out) + 256

    elastic = block.handshake == "elastic"
    if in_value is None:
        in_value = lambda raw: block.data_t(val=raw)
    if out_value is None:
        out_value = lambda d: int(d.val)

    rng = random.Random(seed)
    st = {
        "cycle": 0,
        "idx": 0,
        "presented_valid": 0,
        "ready_now": 1,
        "out_idx": 0,
        "errors": 0,
        "done": False,
        "announced": False,
        "in_hist": [],
        "out_hist": [],
    }

    if elastic:
        in_stream_t = block.in_fwd_t
        in_plain_t = block.in_intrf.stream_t

        @sim_input
        def drive_in() -> in_stream_t:
            if st["idx"] < n_in:
                st["presented_valid"] = 1
                return in_stream_t(
                    stream=in_plain_t(data=in_value(stimulus[st["idx"]]), valid=1)
                )
            st["presented_valid"] = 0
            return in_stream_t(stream=in_plain_t(data=in_value(idle_raw), valid=0))

    else:
        in_stream_t = block.in_stream_t

        @sim_input
        def drive_in() -> in_stream_t:
            if st["idx"] < n_in:
                st["presented_valid"] = 1
                return in_stream_t(data=in_value(stimulus[st["idx"]]), valid=1)
            st["presented_valid"] = 0
            return in_stream_t(data=in_value(idle_raw), valid=0)

    def _ready_value():
        if ready_pattern == "always":
            return 1
        if ready_pattern == "random":
            return 1 if rng.random() < 0.7 else 0
        return 1 if ready_pattern(st["cycle"]) else 0

    out_fb_t = block.out_fb_t

    if elastic:

        @sim_input
        def drive_ready() -> out_fb_t:
            st["ready_now"] = _ready_value()
            return out_fb_t(st["ready_now"])

    else:

        @sim_input
        def drive_ready() -> uint1_t:
            st["ready_now"] = 1
            return 1

    def _announce():
        if not st["announced"]:
            st["announced"] = True
            sim_print(f"=== {name} testbench ===")
            sim_print(f"{name}: {n_in} input samples, {n_out} expected outputs")

    def _check_beat(out_stream):
        got = out_value(out_stream.data)
        if st["out_idx"] >= n_out:
            st["errors"] += 1
            sim_print(f"ERROR: {name}: extra output beat {got} past expected end!")
            raise AssertionError(f"{name}: extra output past expected end")
        exp = expected[st["out_idx"]]
        if got != exp:
            st["errors"] += 1
            sim_print(
                f"ERROR: {name}: output[{st['out_idx']}] expected {exp} got {got}"
            )
            raise AssertionError(f"{name}: output[{st['out_idx']}] {exp} != {got}")
        st["out_hist"].append(got)
        st["out_idx"] += 1
        if st["out_idx"] == n_out and not st["done"]:
            st["done"] = True
            sim_print(f"{name}: all {n_out} outputs matched -- Test DONE!")
            if on_done is not None:
                on_done(st)

    if elastic:

        @sim_output
        def observe(o):
            _announce()
            if st["presented_valid"] and int(o.stream_in_if.ready):
                st["in_hist"].append(stimulus[st["idx"]])
                st["idx"] += 1
            if int(o.stream_out_if.stream.valid) and st["ready_now"]:
                _check_beat(o.stream_out_if.stream)
            st["cycle"] += 1
            assert st["done"] or st["cycle"] < deadline, (
                f"{name}: not done after {st['cycle']} cycles "
                f"({st['idx']}/{n_in} in, {st['out_idx']}/{n_out} out)"
            )

    else:

        @sim_output
        def observe(out_stream):
            _announce()
            if st["presented_valid"]:
                st["in_hist"].append(stimulus[st["idx"]])
                st["idx"] += 1
            if int(out_stream.valid):
                _check_beat(out_stream)
            st["cycle"] += 1
            assert st["done"] or st["cycle"] < deadline, (
                f"{name}: not done after {st['cycle']} cycles "
                f"({st['idx']}/{n_in} in, {st['out_idx']}/{n_out} out)"
            )

    return SimpleNamespace(
        drive_in=drive_in,
        drive_ready=drive_ready,
        observe=observe,
        state=st,
        expected=expected,
        deadline=deadline,
        min_cycles=deadline + 8,
    )
