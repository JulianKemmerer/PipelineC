# pyright: reportInvalidTypeForm=none
"""Testbench library for dsp/fir* filters.

Three layers, all reusable on their own:
  * plain-Python signal generators (impulse/step/sine/two_tone/chirp/noise)
    and `quantize_samples` to turn float signals into raw fixed-point ints;
  * an exact integer golden model (`golden_fir`) -- convolution plus a
    bit-exact mirror of fixed_point.make_fixed_resize's rounding/overflow
    semantics, so comparisons are `==` on raw ints, never float-tolerance;
  * `make_fir_tb(fir, ...)` -- a @sim_input driver (holds each sample until
    accepted, observing the filter's Reg-driven ready), a @sim_input
    ready-stutterer for consumer backpressure, and a @sim_output checker
    (prints the wireguard-style "ERROR: ..." / "... DONE!" convention and
    asserts on mismatch) with optional matplotlib plots.

@sim_input/@sim_output only exist in the native simulator, so a testbench
@MAIN built from these pieces runs under `pypelinec <file> --sim --comb --run N`
(or, calling the native simulator directly, `python3 src/pypeline_sim.py <file> --run N`)
-- never under GHDL/cocotb.

Minimal testbench skeleton (see also src/tests/pypeline_tests/inst/
fir_sim_tb_test.py):

    fir, fir_t = make_fir(...)
    stim = quantize_samples(sine(200, 5), fir.data_t)
    tb = make_fir_tb(fir, stim, ready_pattern="random", name="my_fir")

    @MAIN
    def my_fir_tb():
        stream_in = tb.drive_in()
        out_ready = tb.drive_ready()
        o = fir(stream_in, out_ready)   # out_ready is fir.out_fb_t
        tb.observe(o)

Shared testbench state lives in dicts mutated in place (never rebound):
@sim_input/@sim_output bodies run against detached snapshots of module
globals, so rebinding a name would not be visible across calls.
"""

import math
import os
import random
from types import SimpleNamespace

from pypeline import sim_input, sim_output, sim_print, uint1_t


# ─────────────────────────────────────────────
# Signal generators (plain Python, values in [-amplitude, +amplitude])
# ─────────────────────────────────────────────


def impulse(n, amplitude=0.9):
    return [amplitude if i == 0 else 0.0 for i in range(n)]


def step(n, amplitude=0.5):
    return [amplitude] * n


def sine(n, cycles, amplitude=0.9, phase=0.0):
    """`cycles` full periods across the n samples."""
    return [
        amplitude * math.sin(2.0 * math.pi * cycles * i / n + phase) for i in range(n)
    ]


def two_tone(n, cycles_a, cycles_b, amplitude=0.45):
    """Two equal-amplitude tones (each `amplitude`, so peak <= 2*amplitude)."""
    return [
        amplitude
        * (
            math.sin(2.0 * math.pi * cycles_a * i / n)
            + math.sin(2.0 * math.pi * cycles_b * i / n)
        )
        for i in range(n)
    ]


def chirp(n, cycles_start, cycles_end, amplitude=0.9):
    """Linear frequency sweep from cycles_start to cycles_end periods/n."""
    out = []
    for i in range(n):
        t = i / n
        f = cycles_start + (cycles_end - cycles_start) * t / 2.0
        out.append(amplitude * math.sin(2.0 * math.pi * f * i / n))
    return out


def white_noise(n, rng, amplitude=0.9):
    """Uniform white noise from a caller-seeded random.Random."""
    return [rng.uniform(-amplitude, amplitude) for _ in range(n)]


def quantize_samples(values, data_t):
    """Float samples -> raw fixed-point ints in data_t's representation
    (round-half-even, same as data_t.as_const)."""
    return [int(data_t.as_const(v).val) for v in values]


# ─────────────────────────────────────────────
# Exact integer golden model
# ─────────────────────────────────────────────


def golden_resize(raw, shift, out_total_bits, out_signed, rounding, overflow):
    """Bit-exact Python mirror of fixed_point.make_fixed_resize on a raw
    (already exact, unbounded) Python int."""
    if shift > 0:
        truncated = raw >> shift  # arithmetic shift == floor
        remainder = raw & ((1 << shift) - 1)
        half = 1 << (shift - 1)
        if rounding == "truncate":
            rounded = truncated
        elif rounding == "round_half_up":
            rounded = truncated + 1 if remainder >= half else truncated
        elif rounding == "round_half_even":
            if remainder > half:
                rounded = truncated + 1
            elif remainder < half:
                rounded = truncated
            else:
                rounded = truncated + (truncated & 1)
        elif rounding == "round_half_away":
            if remainder > half:
                rounded = truncated + 1
            elif remainder < half:
                rounded = truncated
            else:
                rounded = truncated if truncated < 0 else truncated + 1
        else:
            raise ValueError(f"golden_resize: unsupported rounding {rounding!r}")
    else:
        rounded = raw << -shift

    if out_signed:
        dst_max = (1 << (out_total_bits - 1)) - 1
        dst_min = -(1 << (out_total_bits - 1))
    else:
        dst_max = (1 << out_total_bits) - 1
        dst_min = 0

    if overflow == "saturate":
        return max(dst_min, min(dst_max, rounded))
    if overflow == "wrap":
        v = rounded & ((1 << out_total_bits) - 1)
        if out_signed and v >= (1 << (out_total_bits - 1)):
            v -= 1 << out_total_bits
        return v
    raise ValueError(f"golden_resize: unsupported overflow {overflow!r}")


def golden_fir(fir, samples_q):
    """Expected raw output ints for a dsp filter built by make_fir /
    make_fir_decim / make_fir_interp, from its metadata attributes.

    samples_q: raw input ints (pre-quantized, e.g. via quantize_samples).
    Models: interp zero-stuffing -> full-rate convolution (window includes the
    current sample) -> output resize -> decim phase selection (outputs fire on
    accepted samples decim-1, 2*decim-1, ...).
    """
    coeffs = fir.coeffs_q
    stuffed = []
    for s in samples_q:
        stuffed.append(s)
        stuffed.extend([0] * (fir.interp - 1))

    shift = fir.accum_t.frac_bits - fir.out_t.frac_bits
    out_total = fir.out_t.int_bits + fir.out_t.frac_bits
    outs = []
    for k in range(len(stuffed)):
        if (k % fir.decim) != fir.decim - 1:
            continue
        acc = 0
        for j in range(len(coeffs)):
            x = stuffed[k - j] if k - j >= 0 else 0
            acc += coeffs[j] * x
        if fir.full_precision:
            outs.append(acc)
        else:
            outs.append(
                golden_resize(
                    acc, shift, out_total, fir.out_t.signed, fir.rounding, fir.overflow
                )
            )
    return outs


# ─────────────────────────────────────────────
# @sim_input / @sim_output testbench factory
# ─────────────────────────────────────────────


def make_fir_tb(
    fir,
    stimulus_q,
    ready_pattern="always",
    seed=8439,
    name="fir",
    plot=False,
    deadline=None,
    expected=None,
):
    """Build the sim-only driver/checker set for one filter instance.

    fir:          the function returned by make_fir/make_fir_decim/
                  make_fir_interp (its metadata attributes are introspected).
    stimulus_q:   raw input ints (see quantize_samples).
    ready_pattern:"always" | "random" (seeded, ~70% ready) | callable(cycle)->bool.
                  Ignored for handshake="valid_only" filters.
    expected:     override the golden expectation (default golden_fir(fir, stimulus_q)).
    deadline:     max cycles before the checker asserts non-completion
                  (default: generous bound from the stimulus size). Run the
                  sim for MORE than tb.deadline cycles (tb.min_cycles).
    plot:         on completion, write <name>_tb.png (input, response, output
                  overlay); set PYPELINE_TB_SHOW=1 to also plt.show().

    Returns SimpleNamespace(drive_in, drive_ready, observe, state, expected,
    deadline, min_cycles).
    """
    if expected is None:
        expected = golden_fir(fir, stimulus_q)
    n_in = len(stimulus_q)
    n_out = len(expected)
    if deadline is None:
        # ~1 cycle/transfer when free-running; x4 margin for random stalls
        # plus slack for pipeline fill and interp output bursts.
        deadline = 4 * (n_in + n_out) + 256

    elastic = fir.handshake == "elastic"
    in_stream_t = fir.in_stream_t
    data_t = fir.data_t

    rng = random.Random(seed)
    st = {
        "cycle": 0,
        "idx": 0,  # next stimulus index to present
        "presented_valid": 0,  # what drive_in presented THIS cycle
        "ready_now": 1,  # what drive_ready returned THIS cycle
        "out_idx": 0,
        "errors": 0,
        "done": False,
        "announced": False,
        "in_hist": [],  # accepted input samples (raw ints)
        "out_hist": [],  # consumed output samples (raw ints)
    }

    @sim_input
    def drive_in() -> in_stream_t:
        # (observe() advanced st["idx"] at the end of the previous cycle if
        # that cycle's presented sample was accepted.)
        if st["idx"] < n_in:
            st["presented_valid"] = 1
            return in_stream_t(data=data_t(val=stimulus_q[st["idx"]]), valid=1)
        st["presented_valid"] = 0
        return in_stream_t(data=data_t(val=0), valid=0)

    def _ready_value():
        if ready_pattern == "always":
            return 1
        if ready_pattern == "random":
            return 1 if rng.random() < 0.7 else 0
        return 1 if ready_pattern(st["cycle"]) else 0

    # drive_ready() yields the output port's *reverse half* so it can be passed
    # straight into the filter's stream_out port.
    out_fb_t = fir.out_fb_t

    if elastic:

        @sim_input
        def drive_ready() -> out_fb_t:
            st["ready_now"] = _ready_value()
            return out_fb_t(ready=st["ready_now"])

    else:

        @sim_input
        def drive_ready() -> uint1_t:
            st["ready_now"] = 1
            return 1

    def _announce():
        if not st["announced"]:
            st["announced"] = True
            sim_print(f"=== FIR testbench '{name}' ===")
            sim_print(f"{name}: {n_in} input samples, {n_out} expected outputs")
            if ready_pattern == "random":
                sim_print(f"{name}: ready_pattern=random seed={seed}")

    def _check_beat(out_stream):
        got = int(out_stream.data.val)
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
            if plot:
                _plot()

    if elastic:

        @sim_output
        def observe(o):
            _announce()
            if st["presented_valid"] and int(o.stream_in.ready):
                st["in_hist"].append(stimulus_q[st["idx"]])
                st["idx"] += 1
            if int(o.stream_out.valid) and st["ready_now"]:
                _check_beat(o.stream_out)
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
                st["in_hist"].append(stimulus_q[st["idx"]])
                st["idx"] += 1
            if int(out_stream.valid):
                _check_beat(out_stream)
            st["cycle"] += 1
            assert st["done"] or st["cycle"] < deadline, (
                f"{name}: not done after {st['cycle']} cycles "
                f"({st['idx']}/{n_in} in, {st['out_idx']}/{n_out} out)"
            )

    def _plot():
        import matplotlib

        if os.environ.get("PYPELINE_TB_SHOW") != "1":
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        in_f = [v / (1 << data_t.frac_bits) for v in st["in_hist"]]
        out_scale = 1 << fir.out_t.frac_bits
        out_f = [v / out_scale for v in st["out_hist"]]
        exp_f = [v / out_scale for v in expected]

        fig, axes = plt.subplots(3, 1, figsize=(10, 9))
        axes[0].plot(in_f)
        axes[0].set_title(f"{name}: input ({len(in_f)} samples)")

        # Frequency response of the quantized taps (normalized).
        coeff_scale = 1 << fir.coeff_t.frac_bits
        taps = [c / coeff_scale for c in fir.coeffs_q]
        nfft = 1024
        mags = []
        for k in range(nfft // 2):
            w = 2.0 * math.pi * k / nfft
            re = sum(t * math.cos(-w * j) for j, t in enumerate(taps))
            im = sum(t * math.sin(-w * j) for j, t in enumerate(taps))
            mags.append(20.0 * math.log10(max(1e-12, math.hypot(re, im))))
        axes[1].plot([k / nfft for k in range(nfft // 2)], mags)
        axes[1].set_title(f"{name}: |H(f)| of quantized taps (dB, f/fs)")

        axes[2].plot(exp_f, label="golden", linewidth=3, alpha=0.4)
        axes[2].plot(out_f, label="hardware", linewidth=1)
        axes[2].legend()
        axes[2].set_title(f"{name}: output ({len(out_f)} samples)")
        fig.tight_layout()
        fname = f"{name}_tb.png"
        fig.savefig(fname)
        sim_print(f"{name}: wrote {fname}")
        if os.environ.get("PYPELINE_TB_SHOW") == "1":
            plt.show()

    return SimpleNamespace(
        drive_in=drive_in,
        drive_ready=drive_ready,
        observe=observe,
        state=st,
        expected=expected,
        deadline=deadline,
        min_cycles=deadline + 8,
    )
