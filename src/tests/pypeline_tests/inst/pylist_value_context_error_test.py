import sys, os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

from pypeline import MAIN, int16_t, int32_t

# Regression test: a genuinely-undefined name subscripted in value context
# (not a hw var, not in const_env, not in module_globals) must raise a clean
# PY_TO_LOGIC.ElaborationError, not a raw KeyError. See pylist_value_context_test.py
# for the supported-construct coverage; this file checks the error path
# _elab_ref_read takes when even the _try_eval_const fallback can't resolve
# the reference. Not run through the pypelinec CLI (unlike
# pylist_value_context_test.py) since the check is "which exception type is
# raised", which needs direct PY_TO_LOGIC.PARSE_FILE + exception-type
# inspection -- same in-process pattern as two_factory_wrappers_test.py.


@MAIN
def m1_undefined_ref(x: int16_t) -> int32_t:
    return x + UNDEFINED_TABLE[0]


def test_undefined_ref_raises_clean_elaboration_error():
    import tempfile
    import PY_TO_LOGIC
    import SYN

    SYN.SYN_OUTPUT_DIRECTORY = tempfile.mkdtemp(
        prefix="pylist_value_context_error_test_"
    )

    try:
        PY_TO_LOGIC.PARSE_FILE(os.path.abspath(__file__))
    except PY_TO_LOGIC.ElaborationError as e:
        assert (
            "undefined_table" in str(e).lower()
        ), f"ElaborationError message should name the offending reference, got: {e}"
        print(f"test_undefined_ref_raises_clean_elaboration_error PASS  ({e})")
        return
    except KeyError as e:
        raise AssertionError(
            f"Expected a clean PY_TO_LOGIC.ElaborationError, got a raw KeyError: {e!r}"
        )
    raise AssertionError(
        "Expected PARSE_FILE to raise ElaborationError, but it succeeded"
    )


if __name__ == "__main__":
    test_undefined_ref_raises_clean_elaboration_error()
    print("All pylist_value_context_error tests passed.")
