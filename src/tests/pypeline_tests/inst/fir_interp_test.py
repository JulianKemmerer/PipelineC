# pyright: reportInvalidTypeForm=none
"""dsp/fir_interp.py tests: make_zero_stuffer beat sequence/backpressure and
make_fir_interp vs golden (zero-stuff + convolve), output ordering, the rate
law (outputs = interp x accepted inputs), and stall recovery."""

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

from pypeline import MAIN, hw_arg_types, uint1_t, sim_call, sim_reset

from fixed_point import make_fixed_t
from dsp.fir_interp import make_fir_interp, make_zero_stuffer
from dsp.fir_tb import golden_fir, quantize_samples, white_noise

data_t = make_fixed_t(1, 7)
coeff_t = make_fixed_t(2, 6)

# gain defaults to interp=3: 3 * max|tap| = 0.703 fits coeff_t's +/-2 range.
TAPS = [0.078125, 0.15625, 0.234375, 0.15625, 0.078125]

interp3, interp3_t = make_fir_interp(
    TAPS,
    coeff_t,
    3,
    data_t,
    out_t=data_t,
    rounding="round_half_even",
    overflow="saturate",
)
stuffer2, stuffer2_t = make_zero_stuffer(data_t, 2)


@MAIN(100.0)
def interp3_main(
    stream_in_if: interp3.in_stream_t, stream_out_if: interp3.out_fb_t
) -> interp3_t:
    return interp3(stream_in_if, stream_out_if)


_MAX_CYCLES = 4000


def _drive_elastic(
    fir, inputs_q, out_ready_fn=lambda c: True, present_fn=lambda c: True
):
    in_stream_t = fir.in_stream_t
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
            in_stream_t(stream=in_stream_t.typeof("stream")(data=fir.data_t(val=d), valid=v)),
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


def _rand_stim(n, seed):
    return quantize_samples(white_noise(n, random.Random(seed)), data_t)


def test_zero_stuffer_beats():
    # 1 input -> [sample, 0] beat pairs, in order, under random backpressure.
    sim_reset()
    stream_t = hw_arg_types(stuffer2)[0]
    plain_t = stream_t.typeof("stream")
    stim = [10, -20, 30]
    stall_rng = random.Random(7)
    idx = 0
    beats = []
    for cycle in range(200):
        v = 1 if idx < len(stim) else 0
        d = stim[idx] if v else 0
        rdy = 1 if stall_rng.random() < 0.6 else 0
        r = sim_call(
            stuffer2,
            stream_t(stream=plain_t(data=data_t(val=d), valid=v)),
            stuffer2.in_fb_t(ready=rdy),
        )
        if v and int(r.stream_in_if.ready):
            idx += 1
        if int(r.stream_out_if.stream.valid) and rdy:
            beats.append(int(r.stream_out_if.stream.data.val))
        if idx >= len(stim) and len(beats) >= 2 * len(stim):
            break
    assert beats == [10, 0, -20, 0, 30, 0], beats
    print("test_zero_stuffer_beats passed")


def test_interp3_matches_golden():
    sim_reset()
    stim = _rand_stim(30, seed=66)
    got = _drive_elastic(interp3, stim)
    exp = golden_fir(interp3, stim)
    assert len(exp) == 3 * len(stim)  # rate law
    assert got == exp, (got, exp)
    print("test_interp3_matches_golden passed")


def test_interp3_stall_recovery():
    sim_reset()
    stim = _rand_stim(25, seed=77)
    stall_rng = random.Random(78)
    got = _drive_elastic(interp3, stim, out_ready_fn=lambda c: stall_rng.random() < 0.5)
    assert got == golden_fir(interp3, stim)
    print("test_interp3_stall_recovery passed")


def test_interp3_input_gaps():
    sim_reset()
    stim = _rand_stim(25, seed=88)
    got = _drive_elastic(interp3, stim, present_fn=lambda c: c % 5 != 3)
    assert got == golden_fir(interp3, stim)
    print("test_interp3_input_gaps passed")


if __name__ == "__main__":
    test_zero_stuffer_beats()
    test_interp3_matches_golden()
    test_interp3_stall_recovery()
    test_interp3_input_gaps()
    print("All fir_interp tests passed.")
