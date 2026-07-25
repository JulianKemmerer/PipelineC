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
from pypeline import MAIN, uint32_t, sim_call, sim_reset

from stream.stream_fifo import make_stream_fifo

# depth=5 rounds up to the real hardware's capacity of 8, same as fifo_test.py.
stream_fifo, stream_fifo_t = make_stream_fifo(uint32_t, 5)
uint32_stream_t = stream_fifo.stream_t
uint32_stream_fb_t = stream_fifo.stream_fb_t
uint32_plain_t = uint32_stream_t.typeof("stream")
CAPACITY = 8


@MAIN
def stream_fifo_test_top(
    in_stream_if: uint32_stream_t, out_stream_if: uint32_stream_fb_t
) -> stream_fifo_t:
    return stream_fifo(in_stream_if, out_stream_if)


def test_stream_fifo_order_and_backpressure():
    """Light coverage of the stream_t field plumbing (.data/.valid <->
    .out_stream_if/.in_stream_if) -- FIFO push/pop/backpressure correctness
    itself is exhaustively covered by fifo_test.py against the shared
    _FifoFwftModel."""
    sim_reset()
    # CAPACITY words fit in the addressed memory the backpressure check is
    # based on, plus one more in the FWFT output register (see fifo_test.py's
    # test_fifo_backpressure_at_capacity) -- CAPACITY + 1 pushes are accepted
    # with no pops before backpressure kicks in.
    values = list(range(1, 1 + CAPACITY + 1))
    for v in values:
        r = sim_call(
            stream_fifo_test_top,
            uint32_stream_t(stream=uint32_plain_t(data=v, valid=1)),
            uint32_stream_fb_t(ready=0),
        )
        assert int(r.in_stream_if.ready) == 1
    # A push attempt while full must backpressure.
    r = sim_call(
        stream_fifo_test_top,
        uint32_stream_t(stream=uint32_plain_t(data=999, valid=1)),
        uint32_stream_fb_t(ready=0),
    )
    assert int(r.in_stream_if.ready) == 0
    popped = []
    for _ in range(len(values)):
        r = sim_call(
            stream_fifo_test_top,
            uint32_stream_t(stream=uint32_plain_t(data=0, valid=0)),
            uint32_stream_fb_t(ready=1),
        )
        assert int(r.out_stream_if.stream.valid) == 1
        popped.append(int(r.out_stream_if.stream.data))
    assert popped == values, f"expected FWFT order {values}, got {popped}"
    r = sim_call(
        stream_fifo_test_top,
        uint32_stream_t(stream=uint32_plain_t(data=0, valid=0)),
        uint32_stream_fb_t(ready=1),
    )
    assert int(r.out_stream_if.stream.valid) == 0, "must be empty after full drain"


if __name__ == "__main__":
    test_stream_fifo_order_and_backpressure()
    print("OK: stream_fifo(...) simulation model behaves correctly")
