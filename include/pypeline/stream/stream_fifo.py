# pyright: reportInvalidTypeForm=none
from pypeline import struct, NamedTuple, hw_func

from fifo import make_fifo
from interface.interface import make_interface_feedback_type, make_interface_type
from stream.stream import make_stream_interface


def make_stream_fifo(data_t, depth: int, mode: str = "fwft"):
    """Stream-shaped FIFO: gives `make_fifo`'s raw (data_in, data_in_valid,
    data_in_ready)/(data_out, data_out_valid, ready_for_data_out) signals a pair
    of stream interface ports. `make_fifo` itself stays raw — its three loose
    signals are literally the wrapped VHDL entity's ports.

    Returns (stream_fifo_func, stream_fifo_t):
        stream_fifo_func(in_stream: stream_t, out_stream: stream_fb_t) -> stream_fifo_t
        stream_fifo_t fields: .out_stream (stream_t), .in_stream (stream_fb_t)
    """
    stream_if = make_stream_interface(data_t)
    stream_t = make_interface_type(stream_if)
    stream_fb_t = make_interface_feedback_type(stream_if)
    fifo_func, fifo_t = make_fifo(data_t, depth, mode)

    @struct
    class stream_fifo_t(NamedTuple):
        out_stream: stream_t
        in_stream: stream_fb_t

    @hw_func
    def stream_fifo(in_stream: stream_t, out_stream: stream_fb_t) -> stream_fifo_t:
        o: stream_fifo_t
        r = fifo_func(out_stream.ready, in_stream.data, in_stream.valid)
        o.out_stream = stream_t(data=r.data_out, valid=r.data_out_valid)
        o.in_stream.ready = r.data_in_ready
        return o

    stream_fifo.stream_if = stream_if
    stream_fifo.stream_t = stream_t
    stream_fifo.stream_fb_t = stream_fb_t
    return stream_fifo, stream_fifo_t
