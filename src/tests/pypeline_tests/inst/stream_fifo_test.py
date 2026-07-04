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
from pypeline import MAIN, uint1_t, uint32_t, sim_call, sim_reset

from stream.stream import make_stream_t
from stream.stream_fifo import make_stream_fifo

uint32_stream_t = make_stream_t(uint32_t)
# depth=5 rounds up to the real hardware's capacity of 8, same as fifo_test.py.
stream_fifo, stream_fifo_t = make_stream_fifo(uint32_t, 5)
CAPACITY = 8


@MAIN
def stream_fifo_test_top(
    out_ready: uint1_t, in_stream: uint32_stream_t
) -> stream_fifo_t:
    return stream_fifo(out_ready, in_stream)


def test_stream_fifo_order_and_backpressure():
    """Light coverage of the stream_t field plumbing (.data/.valid <->
    .out_stream/.in_ready) -- FIFO push/pop/backpressure correctness itself
    is exhaustively covered by fifo_test.py against the shared _FifoFwftModel."""
    sim_reset()
    values = list(range(1, 1 + CAPACITY))
    for v in values:
        r = sim_call(stream_fifo_test_top, 0, uint32_stream_t(data=v, valid=1))
        assert int(r.in_ready) == 1
    # A push attempt while full must backpressure.
    r = sim_call(stream_fifo_test_top, 0, uint32_stream_t(data=999, valid=1))
    assert int(r.in_ready) == 0
    popped = []
    for _ in range(len(values)):
        r = sim_call(stream_fifo_test_top, 1, uint32_stream_t(data=0, valid=0))
        assert int(r.out_stream.valid) == 1
        popped.append(int(r.out_stream.data))
    assert popped == values, f"expected FWFT order {values}, got {popped}"
    r = sim_call(stream_fifo_test_top, 1, uint32_stream_t(data=0, valid=0))
    assert int(r.out_stream.valid) == 0, "must be empty after full drain"


if __name__ == "__main__":
    test_stream_fifo_order_and_backpressure()
    print("OK: stream_fifo(...) simulation model behaves correctly")
