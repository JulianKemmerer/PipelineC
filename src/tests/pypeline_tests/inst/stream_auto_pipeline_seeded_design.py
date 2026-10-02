# pyright: reportInvalidTypeForm=none
"""Build fixture for auto_pipeline_constraints_test.py: a make_stream_auto_pipeline
whose core AUTO_PIPELINE is seeded with start_latency=1 under an easy clock goal.
The bootstrap elaboration serves .latency=1 to the FIFO sizing, the sweep's
first iteration builds exactly 1 core register and meets timing, so the
pypelinec driver must skip the pin-and-confirm re-elaboration (run with
--pipeline_min_effort 0 so trimming can't move the seeded region)."""
import os
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(THIS_DIR, "../../../"))
sys.path.insert(0, os.path.join(THIS_DIR, "../../../../include/pypeline"))

import pypeline
from pypeline import MAIN, hw_func, uint8_t

from stream.stream import make_stream_interface
from stream.stream_auto_pipeline import make_stream_auto_pipeline


@hw_func
def seeded_core(x: uint8_t) -> uint8_t:
    a: uint8_t = (x + 3) / ~x
    return a / (x + 2)


uint8_stream_intrf = make_stream_interface(uint8_t)
seeded_sap, seeded_sap_t = make_stream_auto_pipeline(seeded_core, start_latency=1)
served = sorted(v for vals in pypeline.AUTO_PIPELINE_SERVED_LATENCIES().values() for v in vals)
print(f"stream_auto_pipeline_seeded_design: served .latency={served}", flush=True)


@MAIN(10.0)
def stream_auto_pipeline_seeded_main(
    stream_in_if: uint8_stream_intrf.fwd_t, stream_out_if: uint8_stream_intrf.fb_t
) -> seeded_sap_t:
    return seeded_sap(stream_in_if, stream_out_if)
