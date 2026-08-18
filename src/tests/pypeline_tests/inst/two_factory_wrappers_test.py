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
from pypeline import MAIN, hw_func, int16_t, int32_t, sim_call, sim_reset, uint1_t, uint32_t

from stream.stream import make_stream_interface
from multi_cycle_path import make_valid_ready_mcp

# Regression tests for two variants of the same closure-callable naming
# collision in FuncLogicLookupTable, both undetectable by a plain
# elaboration-succeeds check or by sim_call (native Python, never touches
# FuncLogicLookupTable at all) -- only visible by inspecting
# submodule_instances/canonical names directly after PARSE_FILE:
#
# 1. make_valid_ready_mcp's wrapper calls the caller-supplied function
#    through a closure variable literally named `func`. Two different
#    top-level functions wrapped this way used to collide on that shared
#    alias, so the second wrapper's inner func(...) call silently resolved
#    to the FIRST wrapper's already-elaborated function instead of its own.
#    round_a/round_b share a signature (uint32_t -> uint32_t) so the
#    collision is silent -- no type/assignment error either way -- and
#    PARSE_FILE's Step 6/7 elaborates every top-level @hw_func independently
#    regardless of whether it's ever called by name, so round_a and round_b
#    both get correct, standalone FuncLogicLookupTable entries either way.
#    The bug is only visible in whether anything's submodule_instances
#    actually *instantiates* those entries.
#
# 2. A factory closing over a plain Python list (the FIR-library shape:
#    make_fir(coeffs), symmetric-fold index tables, sign tables) used to
#    raise "Factory closure variable 'coeffs' has unsupported value [...]
#    (type: list). Factory parameters must be C types, ints, bools, None, or
#    callables." from _canonical_func_name (src/PY_TO_LOGIC.py) the moment a
#    second differently-parameterized instance needed a distinct canonical
#    entity name -- same underlying symptom (a naming collision hidden
#    behind same-signature closures), different cause (list closure params
#    weren't encoded into the canonical name at all, vs. case 1's shared
#    fixed alias).
#
# Checked directly, in-process, via PY_TO_LOGIC.PARSE_FILE.


@hw_func
def round_a(x: uint32_t) -> uint32_t:
    return x + 1


@hw_func
def round_b(x: uint32_t) -> uint32_t:
    return (x * 2) + 3


uint32_stream_intrf = make_stream_interface(uint32_t)
a_mcp, a_mcp_t = make_valid_ready_mcp(round_a, 2)
b_mcp, b_mcp_t = make_valid_ready_mcp(round_b, 2)


@MAIN(50.0)
def a_main(
    stream_in_if: uint32_stream_intrf.fwd_t, stream_out_if: a_mcp.out_fb_t
) -> a_mcp_t:
    return a_mcp(stream_in_if, stream_out_if)


@MAIN(50.0)
def b_main(
    stream_in_if: uint32_stream_intrf.fwd_t, stream_out_if: b_mcp.out_fb_t
) -> b_mcp_t:
    return b_mcp(stream_in_if, stream_out_if)


def test_two_factory_wrappers_distinct_logic():
    import tempfile

    import PY_TO_LOGIC
    import SYN

    # PARSE_FILE walks C-built-in submodule instances (Reg[T]/MUX/etc, used
    # internally by make_valid_ready_mcp) via _build_inst_lookup, which needs
    # SYN.SYN_OUTPUT_DIRECTORY set -- normally done by the pypelinec CLI
    # wrapper (src/pypelinec) before it calls PARSE_FILE; replicate that here
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


def make_dot(coeffs):
    n = len(coeffs)

    @hw_func
    def dot(arr: int16_t[4]) -> int32_t:
        acc: int32_t = 0
        for j in range(n):
            acc = acc + arr[j] * coeffs[j]
        return acc

    return dot


COEFFS_A = [3, -5, 7, 2]
COEFFS_B = [1, 1, -1, 4]
dot_a = make_dot(COEFFS_A)
dot_b = make_dot(COEFFS_B)


@MAIN
def dot_a_main(arr: int16_t[4]) -> int32_t:
    return dot_a(arr)


@MAIN
def dot_b_main(arr: int16_t[4]) -> int32_t:
    return dot_b(arr)


def test_two_list_parameterized_instances_get_distinct_logic():
    # A naming collision between dot_a/dot_b would be silent -- both share the
    # same int16_t[4] -> int32_t signature, so no type/assignment error either
    # side -- same reasoning as test_two_factory_wrappers_distinct_logic
    # above. Checked directly, in-process, via PY_TO_LOGIC.PARSE_FILE +
    # FuncLogicLookupTable inspection.
    import tempfile

    import PY_TO_LOGIC
    import SYN

    SYN.SYN_OUTPUT_DIRECTORY = tempfile.mkdtemp(prefix="factory_closure_list_test_")
    parser_state = PY_TO_LOGIC.PARSE_FILE(os.path.abspath(__file__))

    canonical_names = {
        logic.func_name
        for logic in parser_state.FuncLogicLookupTable.values()
        if logic.func_name is not None and logic.func_name.startswith("dot_coeffs_")
    }
    assert "dot_coeffs_3_neg5_7_2" in canonical_names, canonical_names
    assert "dot_coeffs_1_1_neg1_4" in canonical_names, canonical_names

    instantiated = set()
    for logic in parser_state.FuncLogicLookupTable.values():
        instantiated.update(logic.submodule_instances.values())
    assert "dot_coeffs_3_neg5_7_2" in instantiated, (
        "dot_a's Logic() is never instantiated -- dot_a_main's call must have "
        "resolved to a different (colliding) entity instead"
    )
    assert "dot_coeffs_1_1_neg1_4" in instantiated, (
        "dot_b's Logic() is never instantiated -- dot_b_main's call must have "
        "resolved to a different (colliding) entity instead"
    )
    print("test_two_list_parameterized_instances_get_distinct_logic PASS")


def test_list_parameterized_factory_matches_golden_in_sim():
    # sim_call (Layer 1, native Python) never exercises _canonical_func_name at
    # all, so this doesn't test the naming fix above -- it proves the source
    # construct itself (list closure var read via coeffs[j]) still behaves
    # correctly, same as it always has.
    sim_reset()
    arr = [10, -20, 30, 4]
    expected_a = sum(a * c for a, c in zip(arr, COEFFS_A))
    expected_b = sum(a * c for a, c in zip(arr, COEFFS_B))
    result_a = sim_call(dot_a_main, arr=arr)
    result_b = sim_call(dot_b_main, arr=arr)
    assert int(result_a) == expected_a, f"expected {expected_a}, got {int(result_a)}"
    assert int(result_b) == expected_b, f"expected {expected_b}, got {int(result_b)}"
    print(
        "test_list_parameterized_factory_matches_golden_in_sim PASS  "
        f"result_a={int(result_a)} result_b={int(result_b)}"
    )


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
