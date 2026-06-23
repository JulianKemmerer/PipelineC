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
from pypeline import MAIN, hw_func, uint1_t, uint8_t, sim_call

from stream.stream import make_stream_t
from stream.stream_pipeline import make_stream_pipeline


@hw_func
def div_inv(x: uint8_t) -> uint8_t:
    return x / ~x


uint8_stream_t = make_stream_t(uint8_t)
stream_pipeline, stream_pipeline_t = make_stream_pipeline(div_inv, MAX_IN_FLIGHT=4)


@MAIN(50.0)
def stream_pipeline_test_top(
    stream_in: uint8_stream_t, ready_for_stream_out: uint1_t
) -> stream_pipeline_t:
    return stream_pipeline(stream_in, ready_for_stream_out)


def test_stream_pipeline_sim_raises():
    try:
        sim_call(stream_pipeline_test_top, uint8_stream_t(data=0, valid=0), 1)
    except NotImplementedError:
        return
    raise AssertionError("expected NotImplementedError from vhdl(...) simulation")


if __name__ == "__main__":
    test_stream_pipeline_sim_raises()
    print("OK: stream_pipeline(...) simulation correctly raises NotImplementedError")
