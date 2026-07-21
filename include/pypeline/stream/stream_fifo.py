# pyright: reportInvalidTypeForm=none
from pypeline import struct, NamedTuple, uint1_t, hw_func

from fifo import make_fifo
from stream.stream import make_stream_t


def make_stream_fifo(data_t, depth: int, mode: str = "fwft"):
    """Stream-shaped FIFO: wraps make_fifo's raw (data_in, data_in_valid)/(data_out,
    data_out_valid) signature in make_stream_t(data_t) stream_t structs.

    Returns (stream_fifo_func, stream_fifo_t):
        stream_fifo_func(out_ready: uint1_t, in_stream: stream_t) -> stream_fifo_t
        stream_fifo_t fields: .out_stream (stream_t), .in_ready (uint1_t)
    """
    stream_t = make_stream_t(data_t)
    fifo_func, fifo_t = make_fifo(data_t, depth, mode)

    @struct
    class stream_fifo_t(NamedTuple):
        out_stream: stream_t
        in_ready: uint1_t

    @hw_func
    def stream_fifo(out_ready: uint1_t, in_stream: stream_t) -> stream_fifo_t:
        o: stream_fifo_t
        r = fifo_func(out_ready, in_stream.data, in_stream.valid)
        o.out_stream = stream_t(data=r.data_out, valid=r.data_out_valid)
        o.in_ready = r.data_in_ready
        return o

    return stream_fifo, stream_fifo_t
