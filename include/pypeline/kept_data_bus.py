# pyright: reportInvalidTypeForm=none
from pypeline import struct, NamedTuple, uint1_t


def make_kept_data_bus_t(data_t, n):
    """N lanes of data_t with a per-lane keep bit.

    Usage:
        axis32_data_bus_t = make_kept_data_bus_t(uint8_t, 4)
    """

    @struct
    class kept_data_bus_t(NamedTuple):
        data: data_t[n]
        keep: uint1_t[n]

    return kept_data_bus_t
