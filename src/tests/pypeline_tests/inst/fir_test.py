# pyright: reportInvalidTypeForm=none
"""dsp/fir.py make_fir tests: impulse/step/random stimulus vs the exact
integer golden model (dsp/fir_tb.golden_fir), symmetry-folded vs unfolded
bit-identity, half-band zero-tap skipping, antisymmetric folding, full
precision mode, valid_only mode, consumer backpressure stalls, and input
valid gaps. Plain `python3 fir_test.py` runs the sim_call tests; the @MAIN
entry points below also give `pypelinec fir_test.py --comb` elaboration
coverage of every mode."""

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
import random

from pypeline import MAIN, uint1_t, sim_call, sim_reset

from fixed_point import make_fixed_t
from dsp.fir import make_fir
from dsp.fir_tb import golden_fir, impulse, quantize_samples, white_noise

data_t = make_fixed_t(1, 7)  # Q1.7 samples
coeff_t = make_fixed_t(2, 6)  # Q2.6 coefficients

SYM_TAPS = [0.25, 0.5, 0.5, 0.25]  # symmetric, even N
HALFBAND_TAPS = [-0.03125, 0.0, 0.28125, 0.5, 0.28125, 0.0, -0.03125]
ANTISYM_TAPS = [0.25, 0.5, 0.0, -0.5, -0.25]  # antisymmetric, odd N

fir_sym, fir_sym_t = make_fir(
    SYM_TAPS,
    coeff_t,
    data_t,
    out_t=data_t,
    rounding="round_half_even",
    overflow="saturate",
)
fir_nosym, fir_nosym_t = make_fir(
    SYM_TAPS,
    coeff_t,
    data_t,
    out_t=data_t,
    rounding="round_half_even",
    overflow="saturate",
    symmetry="none",
)
fir_hb, fir_hb_t = make_fir(
    HALFBAND_TAPS,
    coeff_t,
    data_t,
    out_t=data_t,
    rounding="round_half_up",
    overflow="saturate",
)
fir_anti, fir_anti_t = make_fir(
    ANTISYM_TAPS,
    coeff_t,
    data_t,
    out_t=data_t,
    rounding="truncate",
    overflow="wrap",
)
fir_full, fir_full_t = make_fir([0.5, -0.25, 0.125], coeff_t, data_t)  # full precision
fir_vonly, fir_vonly_t = make_fir(
    SYM_TAPS,
    coeff_t,
    data_t,
    out_t=data_t,
    rounding="round_half_even",
    overflow="saturate",
    handshake="valid_only",
)


@MAIN(100.0)
def fir_sym_main(
    stream_in_if: fir_sym.in_fwd_t, stream_out_if: fir_sym.out_fb_t
) -> fir_sym_t:
    return fir_sym(stream_in_if, stream_out_if)


@MAIN(100.0)
def fir_hb_main(
    stream_in_if: fir_hb.in_fwd_t, stream_out_if: fir_hb.out_fb_t
) -> fir_hb_t:
    return fir_hb(stream_in_if, stream_out_if)


@MAIN(100.0)
def fir_anti_main(
    stream_in_if: fir_anti.in_fwd_t, stream_out_if: fir_anti.out_fb_t
) -> fir_anti_t:
    return fir_anti(stream_in_if, stream_out_if)


@MAIN(100.0)
def fir_full_main(
    stream_in_if: fir_full.in_fwd_t, stream_out_if: fir_full.out_fb_t
) -> fir_full_t:
    return fir_full(stream_in_if, stream_out_if)


@MAIN(100.0)
def fir_vonly_main(stream_in_if: fir_vonly.in_stream_t) -> fir_vonly_t:
    return fir_vonly(stream_in_if)


_MAX_CYCLES = 3000


def _drive_elastic(
    fir, inputs_q, out_ready_fn=lambda c: True, present_fn=lambda c: True
):
    """Present inputs_q in order (held until accepted), drive consumer ready
    per out_ready_fn(cycle) and input availability per present_fn(cycle);
    return the consumed output sequence (raw ints)."""
    idx = 0
    outputs = []
    expected_n = len(golden_fir(fir, inputs_q))
    for cycle in range(_MAX_CYCLES):
        have = idx < len(inputs_q) and present_fn(cycle)
        v = 1 if have else 0
        d = inputs_q[idx] if have else 0
        rdy = 1 if out_ready_fn(cycle) else 0
        r = sim_call(
            fir,
            fir.in_fwd_t(stream=fir.in_intrf.stream_t(data=fir.data_t(val=d), valid=v)),
            fir.out_fb_t(ready=rdy),
        )
        if v and int(r.stream_in_if.ready):
            idx += 1
        if int(r.stream_out_if.stream.valid) and rdy:
            outputs.append(int(r.stream_out_if.stream.data.val))
        if idx >= len(inputs_q) and len(outputs) >= expected_n:
            return outputs
    raise AssertionError(
        f"filter did not flush in {_MAX_CYCLES} cycles: "
        f"{idx}/{len(inputs_q)} in, {len(outputs)}/{expected_n} out"
    )


def _drive_valid_only(fir, inputs_q):
    outputs = []
    expected_n = len(golden_fir(fir, inputs_q))
    for cycle in range(_MAX_CYCLES):
        if cycle < len(inputs_q):
            v, d = 1, inputs_q[cycle]
        else:
            v, d = 0, 0
        r = sim_call(fir, fir.in_stream_t(data=fir.data_t(val=d), valid=v))
        if int(r.valid):
            outputs.append(int(r.data.val))
        if len(outputs) >= expected_n:
            return outputs
    raise AssertionError(f"valid_only filter did not flush in {_MAX_CYCLES} cycles")


def _rand_stim(n, seed):
    return quantize_samples(white_noise(n, random.Random(seed)), data_t)


def test_impulse_recovers_response():
    sim_reset()
    stim = quantize_samples(impulse(10), data_t)
    got = _drive_elastic(fir_sym, stim)
    assert got == golden_fir(fir_sym, stim), (got, golden_fir(fir_sym, stim))
    print("test_impulse_recovers_response passed")


def test_random_stim_matches_golden():
    sim_reset()
    stim = _rand_stim(60, seed=101)
    got = _drive_elastic(fir_sym, stim)
    assert got == golden_fir(fir_sym, stim)
    print("test_random_stim_matches_golden passed")


def test_symmetry_fold_bit_identical():
    # Folded (2 mults) and unfolded (4 mults) must be bit-identical.
    stim = _rand_stim(50, seed=202)
    sim_reset()
    got_sym = _drive_elastic(fir_sym, stim)
    sim_reset()
    got_nosym = _drive_elastic(fir_nosym, stim)
    assert got_sym == got_nosym
    assert got_sym == golden_fir(fir_sym, stim)
    print("test_symmetry_fold_bit_identical passed")


def test_halfband_zero_tap_skip():
    sim_reset()
    stim = _rand_stim(50, seed=303)
    got = _drive_elastic(fir_hb, stim)
    assert got == golden_fir(fir_hb, stim)
    print("test_halfband_zero_tap_skip passed")


def test_antisymmetric_fold():
    sim_reset()
    stim = _rand_stim(50, seed=404)
    got = _drive_elastic(fir_anti, stim)
    assert got == golden_fir(fir_anti, stim)
    print("test_antisymmetric_fold passed")


def test_full_precision():
    sim_reset()
    stim = _rand_stim(40, seed=505)
    got = _drive_elastic(fir_full, stim)
    assert got == golden_fir(fir_full, stim)
    print("test_full_precision passed")


def test_backpressure_stalls():
    # Random consumer stalls must not drop/duplicate/reorder outputs.
    sim_reset()
    stim = _rand_stim(50, seed=606)
    stall_rng = random.Random(607)
    got = _drive_elastic(fir_sym, stim, out_ready_fn=lambda c: stall_rng.random() < 0.6)
    assert got == golden_fir(fir_sym, stim)
    print("test_backpressure_stalls passed")


def test_input_valid_gaps():
    # Gaps in input valid must freeze the window, not corrupt the sequence.
    sim_reset()
    stim = _rand_stim(40, seed=708)
    got = _drive_elastic(fir_sym, stim, present_fn=lambda c: c % 3 != 2)
    assert got == golden_fir(fir_sym, stim)
    print("test_input_valid_gaps passed")


def test_valid_only_mode():
    sim_reset()
    stim = _rand_stim(50, seed=809)
    got = _drive_valid_only(fir_vonly, stim)
    assert got == golden_fir(fir_vonly, stim)
    print("test_valid_only_mode passed")


if __name__ == "__main__":
    test_impulse_recovers_response()
    test_random_stim_matches_golden()
    test_symmetry_fold_bit_identical()
    test_halfband_zero_tap_skip()
    test_antisymmetric_fold()
    test_full_precision()
    test_backpressure_stalls()
    test_input_valid_gaps()
    test_valid_only_mode()
    print("All fir tests passed.")
