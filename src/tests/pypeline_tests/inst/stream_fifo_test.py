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
from pypeline import MAIN, uint1_t, uint32_t, sim_call

from stream.stream import make_stream_t
from stream.stream_fifo import make_stream_fifo

uint32_stream_t = make_stream_t(uint32_t)
stream_fifo, stream_fifo_t = make_stream_fifo(uint32_t, 256)


@MAIN
def stream_fifo_test_top(
    out_ready: uint1_t, in_stream: uint32_stream_t
) -> stream_fifo_t:
    return stream_fifo(out_ready, in_stream)


def test_stream_fifo_sim_raises():
    try:
        sim_call(stream_fifo_test_top, 1, uint32_stream_t(data=0, valid=0))
    except NotImplementedError:
        return
    raise AssertionError("expected NotImplementedError from vhdl(...) simulation")


if __name__ == "__main__":
    test_stream_fifo_sim_raises()
    print("OK: stream_fifo(...) simulation correctly raises NotImplementedError")
