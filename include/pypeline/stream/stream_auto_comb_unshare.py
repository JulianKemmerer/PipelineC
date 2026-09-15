"""Delay-optimized combinational core between two elastic registers."""
from pypeline import AUTO_COMB_UNSHARE
from stream.stream_auto_comb_share import _make_stream_auto_comb


def make_stream_auto_comb_unshare(func):
    """Return (stream function, return type); latency 2, unstalled II 1."""
    acu = func if type(func) is AUTO_COMB_UNSHARE else AUTO_COMB_UNSHARE(func)
    stream, result_t = _make_stream_auto_comb(acu)
    stream.acu = acu
    return stream, result_t
