# pyright: reportInvalidTypeForm=none
"""Build fixture for latency_memory_build_test.py: one named stream
AUTO_PIPELINE ("core") whose function a design parameter swaps for a much
lighter one, so a latency remembered for the heavy function is stale for the
light one under the same tag key."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "include", "pypeline")
)
from pypeline import MAIN, hw_func, param, uint8_t  # noqa: E402

from stream.stream import make_stream_interface  # noqa: E402
from stream.stream_auto_pipeline import make_stream_auto_pipeline  # noqa: E402

HEAVY = param("LATENCY_MEMORY_HEAVY", 1, choices=(0, 1), help="the heavy core, else the light one")


@hw_func
def heavy_core(x: uint8_t) -> uint8_t:
    a: uint8_t = x / ~x
    return a


@hw_func
def light_core(x: uint8_t) -> uint8_t:
    return x + 1


uint8_stream_intrf = make_stream_interface(uint8_t)
core_pipeline, core_pipeline_t = make_stream_auto_pipeline(
    heavy_core if HEAVY else light_core, name="core"
)


@MAIN(param("LATENCY_MEMORY_GOAL", 50.0, type=float))
def latency_memory_stale_top(
    stream_in_if: uint8_stream_intrf.fwd_t, stream_out_if: uint8_stream_intrf.fb_t
) -> core_pipeline_t:
    return core_pipeline(stream_in_if, stream_out_if)
