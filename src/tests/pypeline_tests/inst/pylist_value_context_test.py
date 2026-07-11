import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

from pypeline import MAIN, hw_func, int16_t, int32_t, sim_call, sim_reset

# Regression test for a value-context read of a plain Python list (module-level
# or closure constant) inside a hw body -- previously crashed the elaborator
# with a raw KeyError ('CQ' treated as an undeclared hardware variable), even
# though native sim already evaluated it correctly (sim runs hw bodies as
# plain Python with no hardware/constant distinction at all). The same
# construct already worked in INDEX context (arr[IDX[j]]) via
# _try_eval_const-based constant folding in _parse_ref_toks; _elab_ref_read
# now falls back to the same mechanism for VALUE context, mirroring the
# fallback _elab_name already had for bare-name reads.

CQ = [3, -5, 7, 2]


@MAIN
def dot_product_module_global(x: int16_t) -> int32_t:
    acc: int32_t = 0
    for j in range(4):
        acc = acc + x * CQ[j]
    return acc


def _make_dot_product_closure():
    coeffs = [10, -20, 30, -40]

    @hw_func
    def dot_product_closure(x: int16_t) -> int32_t:
        acc: int32_t = 0
        for j in range(4):
            acc = acc + x * coeffs[j]
        return acc

    return dot_product_closure


dot_product_closure = _make_dot_product_closure()


@MAIN
def dot_product_closure_main(x: int16_t) -> int32_t:
    return dot_product_closure(x)


def test_module_global_list_value_context():
    sim_reset()
    x = 5
    expected = sum(x * c for c in CQ)
    result = sim_call(dot_product_module_global, x=x)
    assert int(result) == expected, f"expected {expected}, got {int(result)}"
    print(f"test_module_global_list_value_context PASS  result={int(result)}")


def test_closure_list_value_context():
    sim_reset()
    x = 7
    coeffs = [10, -20, 30, -40]
    expected = sum(x * c for c in coeffs)
    result = sim_call(dot_product_closure_main, x=x)
    assert int(result) == expected, f"expected {expected}, got {int(result)}"
    print(f"test_closure_list_value_context PASS  result={int(result)}")


if __name__ == "__main__":
    test_module_global_list_value_context()
    test_closure_list_value_context()
    print("All pylist_value_context tests passed.")
