# pyright: reportInvalidTypeForm=none
"""A bit store into an integer at a hardware index, x[i] = v, is an
ElaborationError that names it.

The bit index of an integer must be a compile-time constant
(PY_TO_LOGIC.FuncElaborator._bit_bounds). Before the fix, a hardware index
reached _emit_var_ref_assign, which indexed the integer as an array and stopped
with "ValueError: substring not found" (#362). The error suggests the
workaround that bit_store_test.py runs in native simulation and GHDL.

Registered in elab_introspect: the design is written to a temp dir and parsed
in process with PY_TO_LOGIC.PARSE_FILE, with no synthesis.
"""

import os
import sys
import tempfile
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", ".."))

import PY_TO_LOGIC as py  # noqa: E402
import SYN  # noqa: E402

TMP = tempfile.mkdtemp(prefix="bit_store_error_")
SYN.SYN_OUTPUT_DIRECTORY = os.path.join(TMP, "syn_out")


def test_hardware_bit_index_store_is_an_elaboration_error():
    path = os.path.join(TMP, "hw_index_store_design.py")
    with open(path, "w") as fh:
        fh.write(
            textwrap.dedent(
                """\
                from pypeline import MAIN, uint5_t, uint32_t


                @MAIN(50.0)
                def top(x: uint32_t, i: uint5_t) -> uint32_t:
                    y: uint32_t = x
                    y[i] = 0
                    return y
                """
            )
        )
    try:
        py.PARSE_FILE(path)
    except py.ElaborationError as e:
        msg = str(e)
        for part in (
            "Bit store 'y[i] = ...' in func 'top'",
            "hw_index_store_design.py:7",
            "'i' is a hardware value",
            "uint_to_array_le(y, 1)",
        ):
            assert part in msg, (part, msg)
    else:
        raise AssertionError("a store at a hardware bit index elaborated")
    print("test_hardware_bit_index_store_is_an_elaboration_error PASS")


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
