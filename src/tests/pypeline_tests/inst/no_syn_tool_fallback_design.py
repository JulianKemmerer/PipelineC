# pyright: reportInvalidTypeForm=none
"""Build fixture for src_module_import_test.py's no-synthesis-tool fallback
check: a start_latency=1 AUTO_PIPELINE call site whose .latency the design
reads (and prints) at import, and no fixed latency= call site. A synthesizing
build's first parse serves 1; with no tool for the part the build continues as
--comb --no_synth, so the pypelinec driver must re-elaborate and the read
becomes 0."""
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

from pypeline import AUTO_PIPELINE, MAIN, hw_func, uint8_t


@hw_func
def fallback_core(x: uint8_t) -> uint8_t:
    return x + 3


FALLBACK_AP = AUTO_PIPELINE(fallback_core, start_latency=1)
print(f"no_syn_tool_fallback_design: .latency={FALLBACK_AP.latency}", flush=True)


@MAIN(10.0)
def no_syn_tool_fallback_main(x: uint8_t) -> uint8_t:
    return FALLBACK_AP(x)
