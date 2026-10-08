# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none
"""Fixture for design_params_build_test.py's re-elaboration case: a
make_stream_auto_pipeline seeded with start_latency=START under a clock goal
its core cannot meet with START registers, so the pin-and-confirm loop
re-imports the design (pass 2). Every import prints the parameter values it
saw -- a declared param() and an injected -D global -- which must be the
same in every pass. CORE_LATENCY is a direct design read of the bottom-up
value, for the pass report (the factory also reads it, to size its FIFO)."""
from pypeline import MAIN, hw_func, param, uint8_t

from stream.stream import make_stream_interface
from stream.stream_auto_pipeline import make_stream_auto_pipeline

START = param("START", 1)
print(f"DESIGN_PARAMS_IMPORT START={START} TAG={TAG}", flush=True)


@hw_func
def pass2_core(x: uint8_t) -> uint8_t:
    a: uint8_t = x / ~x
    b: uint8_t = a / (x + 1)
    return b / (a + 1)


uint8_stream_intrf = make_stream_interface(uint8_t)
pass2_sap, pass2_sap_t = make_stream_auto_pipeline(pass2_core, start_latency=START)
CORE_LATENCY = pass2_sap.auto_pipeline.latency  # DIRECT_LATENCY_READ


@MAIN(100.0)
def design_params_pass2_main(
    stream_in_if: uint8_stream_intrf.fwd_t, stream_out_if: uint8_stream_intrf.fb_t
) -> pass2_sap_t:
    return pass2_sap(stream_in_if, stream_out_if)
