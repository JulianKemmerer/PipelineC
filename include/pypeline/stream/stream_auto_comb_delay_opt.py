"""Delay-optimized combinational core between two elastic registers."""
from pypeline import AUTO_COMB_DELAY_OPT
from stream.stream_auto_comb_area_opt import _make_stream_auto_comb


def make_stream_auto_comb_delay_opt(func):
    """Return (stream function, return type); latency 2, unstalled II 1."""
    tag = func if type(func) is AUTO_COMB_DELAY_OPT else AUTO_COMB_DELAY_OPT(func)
    return _make_stream_auto_comb(tag)
