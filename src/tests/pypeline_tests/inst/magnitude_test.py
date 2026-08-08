# pyright: reportInvalidTypeForm=none
"""dsp/magnitude.py make_magnitude tests: random I/Q stimulus vs the exact
integer golden model (dsp/dsp_tb.golden_magnitude), full precision vs
resized/saturated output, valid_only mode, consumer backpressure stalls, and
input valid gaps. Plain `python3 magnitude_test.py` runs the sim_call tests;
the @MAIN entry points below also give `pypelinec magnitude_test.py --comb`
elaboration coverage of every mode."""

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

from pypeline import MAIN, sim_call, sim_reset

from fixed_point import make_fixed_t
from dsp.magnitude import make_magnitude
from dsp.dsp_tb import golden_magnitude, quantize_samples, white_noise

data_t = make_fixed_t(1, 15)  # Q1.15 samples

mag_full, mag_full_t = make_magnitude(data_t)  # out_t=None: full precision
mag_resized, mag_resized_t = make_magnitude(
    data_t,
    out_t=make_fixed_t(1, 14, signed=False),
    rounding="round_half_even",
    overflow="saturate",
)
mag_vonly, mag_vonly_t = make_magnitude(data_t, handshake="valid_only")


@MAIN(100.0)
def magnitude_full_main(
    stream_in_if: mag_full.in_fwd_t, stream_out_if: mag_full.out_fb_t
) -> mag_full_t:
    return mag_full(stream_in_if, stream_out_if)


@MAIN(100.0)
def magnitude_resized_main(
    stream_in_if: mag_resized.in_fwd_t, stream_out_if: mag_resized.out_fb_t
) -> mag_resized_t:
    return mag_resized(stream_in_if, stream_out_if)


@MAIN(100.0)
def magnitude_vonly_main(stream_in_if: mag_vonly.in_stream_t) -> mag_vonly_t:
    return mag_vonly(stream_in_if)


_MAX_CYCLES = 3000


def _in_value(block, pair):
    i, q = pair
    return block.complex_t(i=block.data_t(val=i), q=block.data_t(val=q))


def _rand_iq(n, seed_i, seed_q):
    ivals = quantize_samples(white_noise(n, random.Random(seed_i)), data_t)
    qvals = quantize_samples(white_noise(n, random.Random(seed_q)), data_t)
    return list(zip(ivals, qvals))


def _drive_elastic(
    block, inputs, out_ready_fn=lambda c: True, present_fn=lambda c: True
):
    idx = 0
    outputs = []
    expected_n = len(golden_magnitude(block, inputs))
    for cycle in range(_MAX_CYCLES):
        have = idx < len(inputs) and present_fn(cycle)
        v = 1 if have else 0
        d = _in_value(block, inputs[idx] if have else (0, 0))
        rdy = 1 if out_ready_fn(cycle) else 0
        r = sim_call(
            block,
            block.in_fwd_t(stream=block.in_intrf.stream_t(data=d, valid=v)),
            block.out_fb_t(ready=rdy),
        )
        if v and int(r.stream_in_if.ready):
            idx += 1
        if int(r.stream_out_if.stream.valid) and rdy:
            outputs.append(int(r.stream_out_if.stream.data.val))
        if idx >= len(inputs) and len(outputs) >= expected_n:
            return outputs
    raise AssertionError(
        f"filter did not flush in {_MAX_CYCLES} cycles: "
        f"{idx}/{len(inputs)} in, {len(outputs)}/{expected_n} out"
    )


def _drive_valid_only(block, inputs):
    outputs = []
    expected_n = len(golden_magnitude(block, inputs))
    for cycle in range(_MAX_CYCLES):
        if cycle < len(inputs):
            v, pair = 1, inputs[cycle]
        else:
            v, pair = 0, (0, 0)
        r = sim_call(block, block.in_stream_t(data=_in_value(block, pair), valid=v))
        if int(r.valid):
            outputs.append(int(r.data.val))
        if len(outputs) >= expected_n:
            return outputs
    raise AssertionError(f"valid_only block did not flush in {_MAX_CYCLES} cycles")


def test_random_stim_matches_golden():
    sim_reset()
    stim = _rand_iq(60, 101, 102)
    got = _drive_elastic(mag_full, stim)
    assert got == golden_magnitude(mag_full, stim)
    print("test_random_stim_matches_golden passed")


def test_resized_output_matches_golden():
    sim_reset()
    stim = _rand_iq(60, 201, 202)
    got = _drive_elastic(mag_resized, stim)
    assert got == golden_magnitude(mag_resized, stim)
    print("test_resized_output_matches_golden passed")


def test_valid_only_mode():
    sim_reset()
    stim = _rand_iq(50, 301, 302)
    got = _drive_valid_only(mag_vonly, stim)
    assert got == golden_magnitude(mag_vonly, stim)
    print("test_valid_only_mode passed")


def test_backpressure_stalls():
    sim_reset()
    stim = _rand_iq(50, 401, 402)
    stall_rng = random.Random(403)
    got = _drive_elastic(mag_full, stim, out_ready_fn=lambda c: stall_rng.random() < 0.6)
    assert got == golden_magnitude(mag_full, stim)
    print("test_backpressure_stalls passed")


def test_input_valid_gaps():
    sim_reset()
    stim = _rand_iq(40, 501, 502)
    got = _drive_elastic(mag_full, stim, present_fn=lambda c: c % 3 != 2)
    assert got == golden_magnitude(mag_full, stim)
    print("test_input_valid_gaps passed")


if __name__ == "__main__":
    test_random_stim_matches_golden()
    test_resized_output_matches_golden()
    test_valid_only_mode()
    test_backpressure_stalls()
    test_input_valid_gaps()
    print("All magnitude tests passed.")
