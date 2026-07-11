# pyright: reportInvalidTypeForm=none
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import MAIN, hw_func, int16_t, int32_t, sim_call, sim_reset

# Regression test for a factory closing over a plain Python list -- the FIR-
# library shape (make_fir(coeffs), symmetric-fold index tables, sign tables):
# native sim already ran this correctly (sim_call never touches
# _canonical_func_name), but --comb/--no_synth elaboration used to raise
# "Factory closure variable 'coeffs' has unsupported value [...] (type: list).
# Factory parameters must be C types, ints, bools, None, or callables." from
# _canonical_func_name (src/PY_TO_LOGIC.py) the moment a second differently-
# parameterized instance needed a distinct canonical entity name.


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
    # side -- same reasoning as two_factory_wrappers_test.py. Checked directly,
    # in-process, via PY_TO_LOGIC.PARSE_FILE + FuncLogicLookupTable inspection.
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
    test_two_list_parameterized_instances_get_distinct_logic()
    test_list_parameterized_factory_matches_golden_in_sim()
    print("All factory_closure_list tests passed.")
