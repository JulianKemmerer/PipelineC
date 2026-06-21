# pyright: reportInvalidTypeForm=none
from pypeline import struct, NamedTuple, uint1_t


def make_ndarray_fragment_t(frag_t, ndims):
    """One fragment of an N-dimensional array stream: a payload plus one
    end-of-dimension flag per dimension (eod[0] generalizes AXIS tlast).

    Usage:
        video_t = make_ndarray_fragment_t(pixel_t, 2)   # eod[0]=eol, eod[1]=eof
    """

    @struct
    class ndarray_fragment_t(NamedTuple):
        frag: frag_t
        eod: uint1_t[ndims]

    return ndarray_fragment_t
