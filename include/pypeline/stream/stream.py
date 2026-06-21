# pyright: reportInvalidTypeForm=none
from pypeline import struct, NamedTuple, uint1_t


def make_stream_t(data_t):
    """Adds the .valid handshake bit on top of any type.

    Usage:
        axis32_t = make_stream_t(axis32_fragment_t)
    """

    @struct
    class stream_t(NamedTuple):
        data: data_t
        valid: uint1_t

    return stream_t
