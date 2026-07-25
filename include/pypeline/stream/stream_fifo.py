# pyright: reportInvalidTypeForm=none
from pypeline import struct, NamedTuple, hw_func

from fifo import make_fifo
from stream.stream import make_stream_interface, make_stream_t


def make_stream_fifo(data_t, depth: int, mode: str = "fwft"):
    """Stream-shaped FIFO: gives `make_fifo`'s raw (data_in, data_in_valid,
    data_in_ready)/(data_out, data_out_valid, ready_for_data_out) signals a pair
    of stream interface ports. `make_fifo` itself stays raw — its three loose
    signals are literally the wrapped VHDL entity's ports.

    Returns (stream_fifo_func, stream_fifo_t):
        stream_fifo_func(in_stream_if: stream_intrf.fwd_t, out_stream_if: stream_intrf.fb_t) -> stream_fifo_t
        stream_fifo_t fields: .out_stream_if (stream_intrf.fwd_t), .in_stream_if (stream_intrf.fb_t)
    """
    stream_intrf = make_stream_interface(data_t)
    plain_t = make_stream_t(data_t)
    fifo_func, fifo_t = make_fifo(data_t, depth, mode)

    @struct
    class stream_fifo_t(NamedTuple):
        out_stream_if: stream_intrf.fwd_t
        in_stream_if: stream_intrf.fb_t

    @hw_func
    def stream_fifo(
        in_stream_if: stream_intrf.fwd_t, out_stream_if: stream_intrf.fb_t
    ) -> stream_fifo_t:
        o: stream_fifo_t
        r = fifo_func(out_stream_if.ready, in_stream_if.stream.data, in_stream_if.stream.valid)
        o.out_stream_if.stream = plain_t(data=r.data_out, valid=r.data_out_valid)
        o.in_stream_if.ready = r.data_in_ready
        return o

    stream_fifo.stream_intrf = stream_intrf
    stream_fifo.fwd_t = stream_intrf.fwd_t
    stream_fifo.fb_t = stream_intrf.fb_t
    return stream_fifo, stream_fifo_t
