# pyright: reportInvalidTypeForm=none
import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "..",
        "..",
        "include",
        "pypeline",
    ),
)
from typing import NamedTuple
from pypeline import MAIN, PART, hw_func, struct, uint1_t, uint32_t

from stream.stream import make_stream_t
from stream.stream_pipeline import make_stream_pipeline
from multi_cycle_path import make_valid_ready_mcp

# make_valid_ready_mcp's MULTI_CYCLE constraints are only supported by Vivado
# synthesis (see multi_cycle_path.py / valid_ready_mcp_test.py), so this design
# needs a real Xilinx PART to be synth-testable at all.
PART("xc7a35ticsg324-1l")

# Regression test for a closure-callable name collision in FuncLogicLookupTable
# (see two_factory_wrappers_test.py for the same-factory silent-miscompile
# variant). This is the loud-failure variant, matching the shape that actually
# blocked the wireguard-fpga ChaCha20/Poly1305 port: two *different* factories
# (make_valid_ready_mcp + make_stream_pipeline) each wrapping a different
# top-level function, with assignment-incompatible return types. Pre-fix, the
# second wrapper's inner `func` call resolves to the first wrapper's already-
# elaborated function and fails to drive its differently-typed output wires.
# Elaboration succeeding cleanly is the pass condition -- checked via
# `pipelinec ... --no_synth` exit code by elab_tests.py, no sim_call needed
# since make_stream_pipeline doesn't support it.


@struct
class wide_t(NamedTuple):
    a: uint32_t
    b: uint32_t
    c: uint32_t
    d: uint32_t


@hw_func
def scalar_round(x: uint32_t) -> uint32_t:
    return x + 1


@hw_func
def wide_round(x: wide_t) -> wide_t:
    rv: wide_t
    rv.a = x.a + 1
    rv.b = x.b + 1
    rv.c = x.c + 1
    rv.d = x.d + 1
    return rv


uint32_stream_t = make_stream_t(uint32_t)
wide_stream_t = make_stream_t(wide_t)
scalar_mcp, scalar_mcp_t = make_valid_ready_mcp(scalar_round, 2)
wide_pipeline, wide_pipeline_t = make_stream_pipeline(wide_round)


@MAIN(50.0)
def scalar_main(
    stream_in: uint32_stream_t, stream_out: scalar_mcp.out_fb_t
) -> scalar_mcp_t:
    return scalar_mcp(stream_in, stream_out)


@MAIN(50.0)
def wide_main(
    stream_in: wide_stream_t, stream_out: wide_pipeline.out_fb_t
) -> wide_pipeline_t:
    return wide_pipeline(stream_in, stream_out)
