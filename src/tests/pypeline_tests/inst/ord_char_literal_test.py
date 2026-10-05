# pyright: reportInvalidTypeForm=none
"""Scalar character constants in a hardware function body.

1. A bare Python builtin call (`c = ord("A")`, `min(3, 4)`) ran in native sim but
   failed elaboration with "Call to unknown function 'ord'": the bare-name call
   path only looked in module globals, which never hold builtins. A constant
   builtin call now folds to a CONST wire; a builtin on a hardware value gets a
   clear "compile-time constant arguments" error instead.
2. A str literal into a scalar char_t (`c = "A"`) died with internal errors on
   both sides (sim: int("A") ValueError; elaboration: a char[1] wire VHDL
   couldn't assign). Both now raise the same message pointing at ord("A").

Design modules are written to a temp dir and imported per case, so native sim
(sim_call) and elaboration (ELABORATE_LIVE_ROOTS) see the same live functions.
"""
import importlib
import itertools
import os
import sys
import tempfile
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "../../../"))

import pypeline  # noqa: E402
import PY_TO_LOGIC as py  # noqa: E402
import SYN  # noqa: E402

TMP = tempfile.mkdtemp(prefix="ord_char_literal_")
sys.path.insert(0, TMP)
SYN.SYN_OUTPUT_DIRECTORY = os.path.join(TMP, "syn_out")
_counter = itertools.count()

HEADER = """\
# pyright: reportInvalidTypeForm=none
from typing import NamedTuple
from pypeline import MAIN, hw_func, struct, char_t, uint8_t
"""

STR_HINT = "ord('A')"


def _load(body):
    name = f"ord_char_literal_design_{next(_counter)}"
    with open(os.path.join(TMP, f"{name}.py"), "w") as fh:
        fh.write(HEADER + textwrap.dedent(body))
    importlib.invalidate_caches()  # the module file was just written
    return importlib.import_module(name)


def _func_logic(state, func_name):
    for name, logic in state.FuncLogicLookupTable.items():
        if name == func_name or name.endswith("_" + func_name):
            return logic
    raise AssertionError(
        f"{func_name} missing from FuncLogicLookupTable: "
        f"{sorted(state.FuncLogicLookupTable)}"
    )


def _const_values(logic):
    """Integer values of the func's CONST wires (CONST_PREFIX + value + '_' + loc)."""
    vals = set()
    for wire in logic.wires:
        if wire.startswith(py.C_TO_LOGIC.CONST_PREFIX):
            tok = wire[len(py.C_TO_LOGIC.CONST_PREFIX) :].split("_")[0]
            if tok.lstrip("-").isdigit():
                vals.add(int(tok))
    return vals


def _expect_elab_error(fn, must_contain):
    try:
        py.ELABORATE_LIVE_ROOTS([fn])
    except py.ElaborationError as e:
        msg = str(e)
        for token in must_contain:
            assert token in msg, f"expected {token!r} in ElaborationError: {msg}"
        return msg
    raise AssertionError(f"{fn.__name__}: expected an ElaborationError")


def _expect_sim_error(fn, args, must_contain):
    pypeline.sim_reset()
    try:
        pypeline.sim_call(fn, *args)
    except TypeError as e:
        msg = str(e)
        for token in must_contain:
            assert token in msg, f"expected {token!r} in sim TypeError: {msg}"
        return msg
    raise AssertionError(f"{fn.__name__}: expected a sim TypeError")


def test_constant_builtin_calls_fold():
    mod = _load(
        """
        @struct
        class out_t(NamedTuple):
            f: char_t
            g: uint8_t


        @hw_func
        def reassign(x: uint8_t) -> char_t:
            c: char_t = 0
            if x:
                c = ord("A")
            return c


        @hw_func
        def annotated() -> char_t:
            c: char_t = ord("C")
            return c


        @hw_func
        def field(x: uint8_t) -> out_t:
            o: out_t
            o.f = ord("B")
            o.g = min(3, 4) + x
            return o
        """
    )
    pypeline.sim_reset()
    assert int(pypeline.sim_call(mod.reassign, 1)) == 65
    assert int(pypeline.sim_call(mod.annotated)) == 67
    o = pypeline.sim_call(mod.field, 1)
    assert (int(o.f), int(o.g)) == (66, 4), o

    for fn, values in (
        (mod.reassign, {65}),
        (mod.annotated, {67}),
        (mod.field, {66, 3}),
    ):
        logic = _func_logic(py.ELABORATE_LIVE_ROOTS([fn]), fn.__name__)
        got = _const_values(logic)
        assert values <= got, (fn.__name__, values, sorted(got))
    print("test_constant_builtin_calls_fold PASS")


def test_builtin_on_hardware_value_is_clear_error():
    mod = _load(
        """
        @hw_func
        def ord_of_wire(x: char_t) -> uint8_t:
            return ord(x)
        """
    )
    msg = _expect_elab_error(mod.ord_of_wire, ["'ord(...)'", "compile-time constant"])
    print(f"test_builtin_on_hardware_value_is_clear_error PASS  ({msg})")


def test_str_into_scalar_same_error_both_sides():
    mod = _load(
        """
        @hw_func
        def reassign(x: uint8_t) -> char_t:
            c: char_t = 0
            if x:
                c = "A"
            return c


        @hw_func
        def annotated() -> char_t:
            c: char_t = "A"
            return c


        @hw_func
        def returned() -> char_t:
            return "A"


        @hw_func
        def takes_char(c: char_t) -> char_t:
            return c


        @hw_func
        def passes_str() -> char_t:
            return takes_char("A")
        """
    )
    for fn, args in (
        (mod.reassign, (1,)),
        (mod.annotated, ()),
        (mod.returned, ()),
        (mod.passes_str, ()),
    ):
        sim_msg = _expect_sim_error(fn, args, [STR_HINT, "'char'"])
        elab_msg = _expect_elab_error(fn, [STR_HINT, "'char'"])
        assert elab_msg.startswith(sim_msg), (fn.__name__, sim_msg, elab_msg)
    print(f"test_str_into_scalar_same_error_both_sides PASS  ({sim_msg})")


def test_str_into_char_array_still_works():
    mod = _load(
        """
        @hw_func
        def name() -> char_t[4]:
            s: char_t[4] = "AB"
            return s
        """
    )
    pypeline.sim_reset()
    assert str(pypeline.sim_call(mod.name)) == "AB"
    py.ELABORATE_LIVE_ROOTS([mod.name])
    print("test_str_into_char_array_still_works PASS")


if __name__ == "__main__":
    test_constant_builtin_calls_fold()
    test_builtin_on_hardware_value_is_clear_error()
    test_str_into_scalar_same_error_both_sides()
    test_str_into_char_array_still_works()
    print("All ord_char_literal tests passed.")
