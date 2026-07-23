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
from pypeline import MAIN, hw_func, uint1_t, uint32_t

from stream.stream import make_stream_t
from multi_cycle_path import make_valid_ready_mcp

# Regression test for a closure-callable name collision in FuncLogicLookupTable:
# make_valid_ready_mcp's wrapper calls the caller-supplied function through a
# closure variable literally named `func`. Two different top-level functions
# wrapped this way used to collide on that shared alias, so the second
# wrapper's inner func(...) call silently resolved to the FIRST wrapper's
# already-elaborated function instead of its own.
#
# round_a/round_b share a signature (uint32_t -> uint32_t) so the collision is
# silent -- no type/assignment error either way -- and PARSE_FILE's Step 6/7
# elaborates every top-level @hw_func independently regardless of whether it's
# ever called by name, so round_a and round_b both get correct, standalone
# FuncLogicLookupTable entries either way. The bug is only visible in whether
# anything's submodule_instances actually *instantiates* those entries -- so
# neither sim_call (native Python execution, never touches
# FuncLogicLookupTable at all) nor a plain elaboration-succeeds check (same
# signature on both sides means a collision produces no error) can see it.
# Checked directly below, in-process, via PY_TO_LOGIC.PARSE_FILE.


@hw_func
def round_a(x: uint32_t) -> uint32_t:
    return x + 1


@hw_func
def round_b(x: uint32_t) -> uint32_t:
    return (x * 2) + 3


uint32_stream_t = make_stream_t(uint32_t)
a_mcp, a_mcp_t = make_valid_ready_mcp(round_a, 2)
b_mcp, b_mcp_t = make_valid_ready_mcp(round_b, 2)


@MAIN(50.0)
def a_main(stream_in: uint32_stream_t, stream_out: a_mcp.out_fb_t) -> a_mcp_t:
    return a_mcp(stream_in, stream_out)


@MAIN(50.0)
def b_main(stream_in: uint32_stream_t, stream_out: b_mcp.out_fb_t) -> b_mcp_t:
    return b_mcp(stream_in, stream_out)


def test_two_factory_wrappers_distinct_logic():
    import tempfile
    import PY_TO_LOGIC
    import SYN

    # PARSE_FILE walks C-built-in submodule instances (Reg[T]/MUX/etc, used
    # internally by make_valid_ready_mcp) via _build_inst_lookup, which needs
    # SYN.SYN_OUTPUT_DIRECTORY set -- normally done by the pipelinec CLI
    # wrapper (src/pipelinec) before it calls PARSE_FILE; replicate that here
    # since this test calls PARSE_FILE directly.
    SYN.SYN_OUTPUT_DIRECTORY = tempfile.mkdtemp(prefix="two_factory_wrappers_test_")

    parser_state = PY_TO_LOGIC.PARSE_FILE(os.path.abspath(__file__))
    instantiated = set()
    for logic in parser_state.FuncLogicLookupTable.values():
        instantiated.update(logic.submodule_instances.values())
    assert "round_a" in instantiated, (
        "round_a's Logic() is never instantiated by anything -- a_mcp's "
        "wrapper must have resolved its inner func(...) call to a different "
        "(colliding) entity instead"
    )
    assert "round_b" in instantiated, (
        "round_b's Logic() is never instantiated by anything -- b_mcp's "
        "wrapper must have resolved its inner func(...) call to a different "
        "(colliding) entity instead"
    )
    print("test_two_factory_wrappers_distinct_logic PASS")


if __name__ == "__main__":
    test_two_factory_wrappers_distinct_logic()
    print("All two_factory_wrappers tests passed.")
