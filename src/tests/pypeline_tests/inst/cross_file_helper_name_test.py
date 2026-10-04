# pyright: reportInvalidTypeForm=none
"""A sub-file's helper call binds to the function that name means in THAT file.

PARSE_FILE Step 6 pre-registers every discovered file's functions before any is
elaborated: the top file's `step` under "step", an imported file's own `step`
under "<module>_step". A bare call `step(x)` inside the imported file looked up
"step" first, so it bound the top file's function -- at that point still an
empty stub, which crashed trimming with `KeyError: None` (and once elaborated it
would be the wrong hardware). A table entry now counts only when its registered
callable is the one the calling module's name is bound to.

Found while checking a TODO about a @MAIN named after its own module: that
case (`counter.py` defining `@MAIN counter`) was fine. The collision was any
helper name shared by the top file and an imported file.
"""
import importlib
import os
import sys
import tempfile
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "../../../"))

import PY_TO_LOGIC as py  # noqa: E402
import SYN  # noqa: E402

TMP = tempfile.mkdtemp(prefix="cross_file_helper_name_")
sys.path.insert(0, TMP)
SYN.SYN_OUTPUT_DIRECTORY = os.path.join(TMP, "syn_out")


def _write(name, body):
    path = os.path.join(TMP, f"{name}.py")
    with open(path, "w") as fh:
        fh.write(
            "# pyright: reportInvalidTypeForm=none\n"
            "from pypeline import MAIN, Reg, hw_func, uint8_t\n"
            + textwrap.dedent(body)
        )
    importlib.invalidate_caches()
    return path


def _callees(state, func_name):
    return sorted(state.FuncLogicLookupTable[func_name].submodule_instances.values())


def test_sub_file_helper_is_not_the_top_file_helper():
    # A third module's `step`, imported by name into the sub-file, must also
    # win over the top file's `step`.
    _write(
        "cfh_lib",
        """
        @hw_func
        def step(x: uint8_t) -> uint8_t:
            return x + 5
        """,
    )
    _write(
        "cfh_counter",
        """
        from cfh_lib import step as lib_step

        @hw_func
        def step(x: uint8_t) -> uint8_t:
            return x + 1

        @MAIN(100.0)
        def counter() -> uint8_t:
            count: Reg[uint8_t]
            rv = count
            count = step(count)
            return rv
        """,
    )
    _write(
        "cfh_importer",
        """
        from cfh_lib import step

        @MAIN(100.0)
        def importer() -> uint8_t:
            n: Reg[uint8_t]
            rv = n
            n = step(n)
            return rv
        """,
    )
    top = _write(
        "cfh_top",
        """
        import cfh_counter
        import cfh_importer

        @hw_func
        def step(x: uint8_t) -> uint8_t:
            return x + 3

        @MAIN(100.0)
        def top() -> uint8_t:
            c: Reg[uint8_t]
            rv = c
            c = step(c)
            return rv
        """,
    )
    state = py.PARSE_FILE(top)
    assert _callees(state, "cfh_counter_counter") == ["cfh_counter_step"], _callees(
        state, "cfh_counter_counter"
    )
    assert _callees(state, "cfh_importer_importer") == ["cfh_lib_step"], _callees(
        state, "cfh_importer_importer"
    )
    assert _callees(state, "top") == ["step"], _callees(state, "top")


if __name__ == "__main__":
    test_sub_file_helper_is_not_the_top_file_helper()
    print("All cross-file helper name tests passed.")
