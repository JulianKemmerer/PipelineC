# pyright: reportInvalidTypeForm=none
"""dsp/fir_decim.py make_fir_decim tests: golden = every decim-th convolution
output; phase alignment across consumer stalls and input valid gaps;
valid_only mode; decim=1 equivalence with make_fir."""

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
from dsp.fir_decim import make_fir_decim
from dsp.fir_tb import golden_fir, quantize_samples, white_noise

data_t = make_fixed_t(1, 7)
coeff_t = make_fixed_t(2, 6)

TAPS = [0.125, 0.375, 0.375, 0.125]

decim3, decim3_t = make_fir_decim(
    TAPS,
    coeff_t,
    3,
    data_t,
    out_t=data_t,
    rounding="round_half_even",
    overflow="saturate",
)
decim2_vonly, decim2_vonly_t = make_fir_decim(
    TAPS,
    coeff_t,
    2,
    data_t,
    out_t=data_t,
    rounding="round_half_even",
    overflow="saturate",
    handshake="valid_only",
)
decim1, decim1_t = make_fir_decim(
    TAPS,
    coeff_t,
    1,
    data_t,
    out_t=data_t,
    rounding="round_half_even",
    overflow="saturate",
)
fir_ref, fir_ref_t = make_fir(
    TAPS,
    coeff_t,
    data_t,
    out_t=data_t,
    rounding="round_half_even",
    overflow="saturate",
)


@MAIN(100.0)
def decim3_main(
    stream_in_if: decim3.in_stream_t, stream_out_if: decim3.out_fb_t
) -> decim3_t:
    return decim3(stream_in_if, stream_out_if)


@MAIN(100.0)
def decim2_vonly_main(stream_in_if: decim2_vonly.in_stream_t) -> decim2_vonly_t:
    return decim2_vonly(stream_in_if)


_MAX_CYCLES = 3000


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


def test_decim3_matches_golden():
    sim_reset()
    stim = _rand_stim(61, seed=11)  # not a multiple of 3: trailing partial group
    got = _drive_elastic(decim3, stim)
    exp = golden_fir(decim3, stim)
    assert len(exp) == 61 // 3  # 1 output per full decim group
    assert got == exp, (got, exp)
    print("test_decim3_matches_golden passed")


def test_decim3_backpressure_phase_alignment():
    sim_reset()
    stim = _rand_stim(45, seed=22)
    stall_rng = random.Random(23)
    got = _drive_elastic(decim3, stim, out_ready_fn=lambda c: stall_rng.random() < 0.5)
    assert got == golden_fir(decim3, stim)
    print("test_decim3_backpressure_phase_alignment passed")


def test_decim3_input_gaps():
    sim_reset()
    stim = _rand_stim(45, seed=33)
    got = _drive_elastic(decim3, stim, present_fn=lambda c: c % 4 != 1)
    assert got == golden_fir(decim3, stim)
    print("test_decim3_input_gaps passed")


def test_decim2_valid_only():
    sim_reset()
    stim = _rand_stim(50, seed=44)
    in_stream_t = decim2_vonly.in_stream_t
    outputs = []
    expected = golden_fir(decim2_vonly, stim)
    for cycle in range(_MAX_CYCLES):
        if cycle < len(stim):
            v, d = 1, stim[cycle]
        else:
            v, d = 0, 0
        r = sim_call(decim2_vonly, in_stream_t(data=data_t(val=d), valid=v))
        if int(r.valid):
            outputs.append(int(r.data.val))
        if len(outputs) >= len(expected):
            break
    assert outputs == expected, (outputs, expected)
    print("test_decim2_valid_only passed")


def test_decim1_equals_plain_fir():
    stim = _rand_stim(40, seed=55)
    sim_reset()
    got_d1 = _drive_elastic(decim1, stim)
    sim_reset()
    got_fir = _drive_elastic(fir_ref, stim)
    assert got_d1 == got_fir
    assert got_d1 == golden_fir(decim1, stim)
    print("test_decim1_equals_plain_fir passed")


if __name__ == "__main__":
    test_decim3_matches_golden()
    test_decim3_backpressure_phase_alignment()
    test_decim3_input_gaps()
    test_decim2_valid_only()
    test_decim1_equals_plain_fir()
    print("All fir_decim tests passed.")
