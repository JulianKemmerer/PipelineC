# pyright: reportInvalidTypeForm=none
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
from pypeline import MAIN, hw_func, uint1_t, uint8_t, sim_call, sim_reset

from interface.interface import make_interface_feedback_type, make_interface_type
from stream.stream import make_stream_interface
from stream.stream_pipeline import make_stream_pipeline


@hw_func
def div_inv(x: uint8_t) -> uint8_t:
    return x / ~x


uint8_stream_if = make_stream_interface(uint8_t)
uint8_stream_t = make_interface_type(uint8_stream_if)
uint8_stream_fb_t = make_interface_feedback_type(uint8_stream_if)
stream_pipeline, stream_pipeline_t = make_stream_pipeline(div_inv)


@MAIN(50.0)
def stream_pipeline_test_top(
    stream_in: uint8_stream_t, stream_out: uint8_stream_fb_t
) -> stream_pipeline_t:
    return stream_pipeline(stream_in, stream_out)


# Generous safety bound so a real bug (dropped/stuck data) fails fast with a
# clear assertion instead of looping forever.
_MAX_CYCLES = 200


def _drive(input_values, out_ready_fn):
    """Feed input_values into stream_pipeline_test_top in order (holding each
    value steady until accepted, per stream_in.ready), driving out_ready
    per out_ready_fn(cycle), and return the list of stream_out.data values
    observed on cycles where both valid and out_ready held -- i.e. the actual
    accepted output sequence, independent of the pipeline's internal latency.
    """
    idx = 0
    outputs = []
    for cycle in range(_MAX_CYCLES):
        present_valid = 1 if idx < len(input_values) else 0
        present_data = input_values[idx] if present_valid else 0
        out_ready = 1 if out_ready_fn(cycle) else 0
        r = sim_call(
            stream_pipeline_test_top,
            uint8_stream_t(data=present_data, valid=present_valid),
            uint8_stream_fb_t(ready=out_ready),
        )
        if present_valid and int(r.stream_in.ready):
            idx += 1
        if int(r.stream_out.valid) and out_ready:
            outputs.append(int(r.stream_out.data))
        if idx >= len(input_values) and len(outputs) >= len(input_values):
            return outputs
    raise AssertionError(
        f"pipeline did not flush within {_MAX_CYCLES} cycles: "
        f"accepted {idx}/{len(input_values)} inputs, "
        f"observed {len(outputs)}/{len(input_values)} outputs"
    )


def test_stream_pipeline_steady_drain():
    sim_reset()
    # Avoid x=255 -- ~x wraps to 0 for uint8_t, and div_inv's x/~x is a
    # pre-existing division-by-zero landmine for that one input.
    inputs = [3, 7, 1, 9, 2]
    expected = [int(sim_call(div_inv, x)) for x in inputs]
    outputs = _drive(inputs, lambda cycle: True)
    assert outputs == expected, f"expected {expected}, got {outputs}"


def test_stream_pipeline_stall_and_resume():
    sim_reset()
    inputs = [4, 8, 15, 16, 23]
    expected = [int(sim_call(div_inv, x)) for x in inputs]

    def out_ready_fn(cycle):
        return not (3 <= cycle < 8)  # consumer stalls for a few cycles mid-stream

    outputs = _drive(inputs, out_ready_fn)
    assert outputs == expected, f"expected {expected}, got {outputs}"


if __name__ == "__main__":
    test_stream_pipeline_steady_drain()
    test_stream_pipeline_stall_and_resume()
    print("OK: stream_pipeline(...) simulation model behaves correctly")
