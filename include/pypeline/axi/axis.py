# pyright: reportInvalidTypeForm=none
from pypeline import uint1_t, uint8_t, make_uint_t

from kept_data_bus import make_kept_data_bus_t
from ndarray import make_ndarray_fragment_t
from stream.stream import make_stream_t


def make_axis_t(n, elem_t=uint8_t, ndims=1):
    """Composes kept_data_bus_t -> ndarray_fragment_t -> stream_t.

    Only literally AXI-Stream-compliant when elem_t is uint8_t (the default,
    i.e. tdata/tkeep are bytes) — with another elem_t this is the same
    keep-per-lane shape generalized to a per-lane struct stream.

    Usage:
        axis32_t = make_axis_t(4)   # stream(ndarray_fragment(1, kept_data_bus(uint8_t, 4)))
    """
    bus_t = make_kept_data_bus_t(elem_t, n)
    fragment_t = make_ndarray_fragment_t(bus_t, ndims)
    return make_stream_t(fragment_t)


def make_keep_count(bus_t, n):
    """Hardware function: popcount of .keep over n lanes."""
    count_t = make_uint_t(n.bit_length())

    def keep_count(lanes: bus_t) -> count_t:
        rv: count_t = 0
        for i in range(n):
            rv = rv + lanes.keep[i]
        return rv

    return keep_count


def make_count_to_keep(n):
    """Hardware function: lane count -> thermometer-coded keep[n]
    (lanes [0, count) asserted)."""
    count_t = make_uint_t(n.bit_length())
    keep_t = uint1_t[n]

    def count_to_keep(count: count_t) -> keep_t:
        rv: keep_t = [0] * n
        for i in range(n):
            rv[i] = i < count
        return rv

    return count_to_keep
