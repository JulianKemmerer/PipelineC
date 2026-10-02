# pyright: reportInvalidTypeForm=none
"""Build fixture for auto_pipeline_constraints_test.py: a make_stream_auto_pipeline
whose core AUTO_PIPELINE is seeded with start_latency=1 under a clock goal the
core can't meet with 1 register. start_latency is only a starting guess: the
sweep must grow the core past 1, and because the FIFO was sized from the
served 1, the pin-and-confirm pass must re-elaborate with the built count."""
import os
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(THIS_DIR, "../../../"))
sys.path.insert(0, os.path.join(THIS_DIR, "../../../../include/pypeline"))

from pypeline import MAIN, hw_func, uint8_t

from stream.stream import make_stream_interface
from stream.stream_auto_pipeline import make_stream_auto_pipeline


@hw_func
def grow_core(x: uint8_t) -> uint8_t:
    a: uint8_t = x / ~x
    b: uint8_t = a / (x + 1)
    return b / (a + 1)


uint8_stream_intrf = make_stream_interface(uint8_t)
grow_sap, grow_sap_t = make_stream_auto_pipeline(grow_core, start_latency=1)


@MAIN(100.0)
def stream_auto_pipeline_grow_main(
    stream_in_if: uint8_stream_intrf.fwd_t, stream_out_if: uint8_stream_intrf.fb_t
) -> grow_sap_t:
    return grow_sap(stream_in_if, stream_out_if)
