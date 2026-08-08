# pyright: reportInvalidTypeForm=none
"""dsp/dc_block.py make_dc_block tests: random stimulus vs the exact integer
golden model (dsp/dsp_tb.golden_dc_block), full precision vs resized/
saturated output, valid_only mode, consumer backpressure stalls, and input
valid gaps. Plain `python3 dc_block_test.py` runs the sim_call tests; the
@MAIN entry points below also give `pypelinec dc_block_test.py --comb`
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
from dsp.dc_block import make_dc_block
from dsp.dsp_tb import golden_dc_block, quantize_samples, white_noise

data_t = make_fixed_t(1, 15)  # Q1.15 samples

dcb_full, dcb_full_t = make_dc_block(data_t, k=5)  # out_t=None: full precision
dcb_resized, dcb_resized_t = make_dc_block(
    data_t, k=5, out_t=data_t, rounding="round_half_even", overflow="saturate"
)
dcb_vonly, dcb_vonly_t = make_dc_block(data_t, k=5, handshake="valid_only")


@MAIN(100.0)
def dc_block_full_main(
    stream_in_if: dcb_full.in_fwd_t, stream_out_if: dcb_full.out_fb_t
) -> dcb_full_t:
    return dcb_full(stream_in_if, stream_out_if)


@MAIN(100.0)
def dc_block_resized_main(
    stream_in_if: dcb_resized.in_fwd_t, stream_out_if: dcb_resized.out_fb_t
) -> dcb_resized_t:
    return dcb_resized(stream_in_if, stream_out_if)


@MAIN(100.0)
def dc_block_vonly_main(stream_in_if: dcb_vonly.in_stream_t) -> dcb_vonly_t:
    return dcb_vonly(stream_in_if)


_MAX_CYCLES = 6000


def _rand_stim(n, seed):
    return quantize_samples(white_noise(n, random.Random(seed)), data_t)


def _drive_elastic(
    block, inputs, out_ready_fn=lambda c: True, present_fn=lambda c: True
):
    idx = 0
    outputs = []
    expected_n = len(golden_dc_block(block, inputs))
    for cycle in range(_MAX_CYCLES):
        have = idx < len(inputs) and present_fn(cycle)
        v = 1 if have else 0
        d = inputs[idx] if have else 0
        rdy = 1 if out_ready_fn(cycle) else 0
        r = sim_call(
            block,
            block.in_fwd_t(
                stream=block.in_intrf.stream_t(data=block.data_t(val=d), valid=v)
            ),
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
    expected_n = len(golden_dc_block(block, inputs))
    for cycle in range(_MAX_CYCLES):
        if cycle < len(inputs):
            v, d = 1, inputs[cycle]
        else:
            v, d = 0, 0
        r = sim_call(block, block.in_stream_t(data=block.data_t(val=d), valid=v))
        if int(r.valid):
            outputs.append(int(r.data.val))
        if len(outputs) >= expected_n:
            return outputs
    raise AssertionError(f"valid_only block did not flush in {_MAX_CYCLES} cycles")


def test_random_stim_matches_golden():
    sim_reset()
    stim = _rand_stim(80, 111)
    got = _drive_elastic(dcb_full, stim)
    assert got == golden_dc_block(dcb_full, stim)
    print("test_random_stim_matches_golden passed")


def test_resized_output_matches_golden():
    sim_reset()
    stim = _rand_stim(80, 211)
    got = _drive_elastic(dcb_resized, stim)
    assert got == golden_dc_block(dcb_resized, stim)
    print("test_resized_output_matches_golden passed")


def test_valid_only_mode():
    sim_reset()
    stim = _rand_stim(60, 311)
    got = _drive_valid_only(dcb_vonly, stim)
    assert got == golden_dc_block(dcb_vonly, stim)
    print("test_valid_only_mode passed")


def test_backpressure_stalls():
    sim_reset()
    stim = _rand_stim(60, 411)
    stall_rng = random.Random(412)
    got = _drive_elastic(dcb_full, stim, out_ready_fn=lambda c: stall_rng.random() < 0.6)
    assert got == golden_dc_block(dcb_full, stim)
    print("test_backpressure_stalls passed")


def test_input_valid_gaps():
    sim_reset()
    stim = _rand_stim(50, 511)
    got = _drive_elastic(dcb_full, stim, present_fn=lambda c: c % 3 != 2)
    assert got == golden_dc_block(dcb_full, stim)
    print("test_input_valid_gaps passed")


if __name__ == "__main__":
    test_random_stim_matches_golden()
    test_resized_output_matches_golden()
    test_valid_only_mode()
    test_backpressure_stalls()
    test_input_valid_gaps()
    print("All dc_block tests passed.")
