# pyright: reportInvalidTypeForm=none
"""Global Wire/Input/Output names vs. function locals.

Pypeline has no `global` statement: inside the module that declares a wire, the
wire's name always IS the wire (`acc = x` writes it, `acc` reads it). Three
bugs lived around that rule, all silent:

1. A local BINDING of a wire's name (annotated `acc: T = e`, a parameter, a loop
   or comprehension variable, ...) was resolved differently by the two layers:
   native sim rewrote every mention to the wire, elaboration re-declared the wire
   as a local (annotated form) or read the local (parameter / loop variable).
   Now rejected by both: pypeline.GlobalWireNameError at decoration time,
   PY_TO_LOGIC.ElaborationError at elaboration.
2. Elaboration resolved bare names against the process-wide
   parser_state.global_vars, so a local `valid` in an unrelated helper module
   silently became a writer of the top design file's `valid: Wire[T]`. Native
   sim only rewrites the function's own module wires; elaboration now does too.
3. `acc, b = x, y` wrote the wire in elaboration but was a plain Python local
   store in native sim. Sim now lowers it to per-leaf wire writes.

Design modules are written to a temp dir and imported per case, since the sim
error fires at import (decoration) time. Elaboration's own check is reached by
stubbing the sim check out -- otherwise the design can't even be imported.
"""
import importlib
import itertools
import os
import sys
import tempfile
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "../../../"))
sys.path.insert(0, os.path.join(HERE, "..", "def"))

import pypeline  # noqa: E402
import PY_TO_LOGIC as py  # noqa: E402
import SYN  # noqa: E402

TMP = tempfile.mkdtemp(prefix="local_binds_global_wire_")
sys.path.insert(0, TMP)
SYN.SYN_OUTPUT_DIRECTORY = os.path.join(TMP, "syn_out")
_counter = itertools.count()

HEADER = """\
# pyright: reportInvalidTypeForm=none
from typing import NamedTuple
from pypeline import MAIN, Reg, Wire, hw_func, struct, uint8_t
"""


def _write(name, body):
    path = os.path.join(TMP, f"{name}.py")
    with open(path, "w") as fh:
        fh.write(HEADER + textwrap.dedent(body))
    return path


def _fresh(prefix):
    return f"{prefix}_{next(_counter)}"


def _import(name):
    importlib.invalidate_caches()  # the module file was just written
    return importlib.import_module(name)


class _sim_check_disabled:
    """Import a design whose sim-side check would raise, so elaboration's own
    check can be exercised."""

    def __enter__(self):
        self._saved = pypeline._check_no_local_binds_wire_name
        pypeline._check_no_local_binds_wire_name = lambda *a, **k: None

    def __exit__(self, *exc):
        pypeline._check_no_local_binds_wire_name = self._saved


def _func_logic(state, func_name):
    for name, logic in state.FuncLogicLookupTable.items():
        if name == func_name or name.endswith("_" + func_name):
            return logic
    raise AssertionError(
        f"{func_name} missing from FuncLogicLookupTable: "
        f"{sorted(state.FuncLogicLookupTable)}"
    )


# (kind text both errors must name, case label) -> a same-module hw_func `f`
# binding the wire name `acc` locally.
BIND_CASES = {
    ("annotated local", "annotated local with value"): """
        @hw_func
        def f(x: uint8_t) -> uint8_t:
            acc: uint8_t = x + 1
            return acc
    """,
    ("annotated local", "Reg declaration"): """
        @hw_func
        def f(x: uint8_t) -> uint8_t:
            acc: Reg[uint8_t]
            acc = x
            return acc
    """,
    ("parameter", "parameter"): """
        @hw_func
        def f(acc: uint8_t) -> uint8_t:
            return acc
    """,
    ("for-loop variable", "for-loop variable"): """
        @hw_func
        def f(x: uint8_t) -> uint8_t:
            s: uint8_t = x
            for acc in range(3):
                s = s + acc
            return s
    """,
    ("comprehension variable", "comprehension variable"): """
        @hw_func
        def f(x: uint8_t) -> uint8_t:
            n = sum([acc for acc in range(3)])
            return x + n
    """,
}


def _bind_source(body):
    return "acc: Wire[uint8_t]\n" + textwrap.dedent(body)


def test_sim_rejects_local_binding_of_wire_name():
    for (kind, label), body in BIND_CASES.items():
        name = _fresh("bind_sim")
        _write(name, _bind_source(body))
        try:
            _import(name)
        except pypeline.GlobalWireNameError as e:
            msg = str(e)
            assert f"{kind} 'acc'" in msg, (label, msg)
            assert f"{name}.py:" in msg, msg
        else:
            raise AssertionError(f"sim accepted {label} named like a global wire")
    print("test_sim_rejects_local_binding_of_wire_name PASS")


def test_elab_rejects_local_binding_of_wire_name():
    for (kind, label), body in BIND_CASES.items():
        name = _fresh("bind_elab")
        _write(name, _bind_source(body))
        with _sim_check_disabled():
            mod = _import(name)
        try:
            py.ELABORATE_LIVE_ROOTS([mod.f])
        except py.ElaborationError as e:
            msg = str(e.args[0])
            assert f"{kind} 'acc'" in msg, (label, msg)
        else:
            raise AssertionError(f"elaboration accepted {label} named like a wire")
    print("test_elab_rejects_local_binding_of_wire_name PASS")


def test_elab_rejects_through_parse_file():
    """The PARSE_FILE (pypelinec) path, which elaborates every top-level hw_func."""
    name = _fresh("bind_parse")
    path = _write(
        name,
        _bind_source(BIND_CASES[("annotated local", "annotated local with value")])
        + textwrap.dedent(
            """
            @MAIN
            def top(x: uint8_t) -> uint8_t:
                return f(x)
            """
        ),
    )
    with _sim_check_disabled():
        try:
            py.PARSE_FILE(path)
        except py.ElaborationError as e:
            assert "annotated local 'acc'" in str(e.args[0]), e
        else:
            raise AssertionError("PARSE_FILE accepted a local named like a wire")
    print("test_elab_rejects_through_parse_file PASS")


def test_module_alias_binding_rejected():
    """A local named like an imported module that declares wires (file_a) would
    otherwise make `file_a.o` mean the module's wire in one layer only."""
    body = """
        import file_a

        @hw_func
        def g(file_a: uint8_t) -> uint8_t:
            return file_a
    """
    name = _fresh("alias_sim")
    _write(name, body)
    try:
        _import(name)
    except pypeline.GlobalWireNameError as e:
        assert "imported module 'file_a'" in str(e), e
    else:
        raise AssertionError("sim accepted a parameter named like a wire module")
    name = _fresh("alias_elab")
    _write(name, body)
    with _sim_check_disabled():
        mod = _import(name)
    try:
        py.ELABORATE_LIVE_ROOTS([mod.g])
    except py.ElaborationError as e:
        assert "imported module 'file_a'" in str(e.args[0]), e
    else:
        raise AssertionError("elaboration accepted a param named like a wire module")
    print("test_module_alias_binding_rejected PASS")


def test_sub_file_prefix_binding_rejected():
    """In an imported sub-file the wire is registered as '<module>_arr'; its bare
    name 'arr' must still count as the wire there."""
    sub = _fresh("prefix_sub")
    _write(
        sub,
        """
        arr: Wire[uint8_t]

        @hw_func
        def h(x: uint8_t) -> uint8_t:
            arr: uint8_t = x
            return arr
        """,
    )
    top = _fresh("prefix_top")
    path = _write(
        top,
        f"""
        import {sub}

        @MAIN
        def top(x: uint8_t) -> uint8_t:
            return {sub}.h(x)
        """,
    )
    try:
        _import(top)
    except pypeline.GlobalWireNameError as e:
        assert "'arr'" in str(e), e
    else:
        raise AssertionError("sim accepted a sub-file local named like its wire")
    sys.modules.pop(sub, None)
    sys.modules.pop(top, None)
    with _sim_check_disabled():
        try:
            py.PARSE_FILE(path)
        except py.ElaborationError as e:
            msg = str(e.args[0])
            assert "annotated local 'arr'" in msg, msg
        else:
            raise AssertionError("elaboration accepted a sub-file local named arr")
    print("test_sub_file_prefix_binding_rejected PASS")


def test_other_module_local_is_not_the_wire():
    """A local in a module that does NOT declare the wire stays a local, even when
    the top design file declares a same-named wire -- or a sub-file wire whose
    registered key is spelled the same ('file_a_o')."""
    helper = _fresh("xmod_helper")
    _write(
        helper,
        """
        @hw_func
        def helper(x: uint8_t) -> uint8_t:
            valid: uint8_t = x + 1
            return valid

        @hw_func
        def helper_plain(x: uint8_t) -> uint8_t:
            valid = x + 2
            file_a_o = valid + 1
            return file_a_o
        """,
    )
    top = _fresh("xmod_top")
    path = _write(
        top,
        f"""
        import file_a
        from pypeline import uint1_t
        from {helper} import helper, helper_plain

        valid: Wire[uint8_t]

        @MAIN
        def top(x: uint8_t) -> uint8_t:
            return helper(x) + helper_plain(x)

        @MAIN
        def drive(x: uint8_t):
            valid = x

        @MAIN
        def drive_file_a(x: uint1_t):
            file_a.i = x  # file_a.i needs a writer for PARSE_FILE

        @MAIN
        def read() -> uint8_t:
            return valid
        """,
    )
    mod = _import(top)
    pypeline.sim_reset()
    assert int(pypeline.sim_call(mod.top, 5)) == 6 + 8

    def check(state, how):
        for fname in ("helper", "helper_plain"):
            logic = _func_logic(state, fname)
            assert not logic.write_only_global_wires, (
                how, fname, list(logic.write_only_global_wires))
            assert not logic.read_only_global_wires, (
                how, fname, list(logic.read_only_global_wires))
            assert not [w for w in logic.wires if "PYPELINE_READBACK" in w], (
                how, fname)
        writers = [
            n for n, l in state.FuncLogicLookupTable.items()
            if "valid" in getattr(l, "write_only_global_wires", {})
        ]
        assert writers == ["drive"], (how, writers)

    check(py.ELABORATE_LIVE_ROOTS([mod.top, mod.drive]), "live")
    check(py.PARSE_FILE(path), "parse")
    print("test_other_module_local_is_not_the_wire PASS")


def test_same_module_write_still_drives_wire():
    """Positive control: the ordinary no-`global` write is unchanged."""
    name = _fresh("plain_write")
    _write(
        name,
        """
        acc: Wire[uint8_t]

        @MAIN
        def writer(x: uint8_t):
            acc = x + 1

        @MAIN
        def reader() -> uint8_t:
            return acc
        """,
    )
    mod = _import(name)
    pypeline.sim_reset()
    pypeline.sim_call(mod.writer, 4)
    assert int(pypeline.sim_call(mod.reader)) == 5
    state = py.ELABORATE_LIVE_ROOTS([mod.writer, mod.reader])
    assert "acc" in _func_logic(state, "writer").write_only_global_wires
    assert "acc" in _func_logic(state, "reader").read_only_global_wires
    print("test_same_module_write_still_drives_wire PASS")


def test_unpack_into_wire_writes_it_in_sim():
    name = _fresh("unpack")
    _write(
        name,
        """
        acc: Wire[uint8_t]
        acc2: Wire[uint8_t]

        @MAIN
        def writer(x: uint8_t, en: uint8_t):
            b: uint8_t = 0
            if en:
                acc, b = x, x + 250
                b, acc2 = acc, b

        @MAIN
        def reader() -> uint8_t:
            return acc + acc2
        """,
    )
    mod = _import(name)
    pypeline.sim_reset()
    pypeline.sim_call(mod.writer, 10, 1)
    # acc=10; b=(10+250)&0xff=4 (typed local still truncated); then the RHS is
    # evaluated before either target: b=acc=10, acc2=old b=4.
    assert int(pypeline.sim_call(mod.reader)) == 10 + 4
    state = pypeline._sim_wire_state
    assert state[f"{name}.acc"] == 10, dict(state)
    # Unpacking is a claimed write: the next invocation starts from zero again.
    pypeline.sim_call(mod.writer, 10, 0)
    assert int(pypeline.sim_call(mod.reader)) == 0

    logic = _func_logic(py.ELABORATE_LIVE_ROOTS([mod.writer]), "writer")
    assert {"acc", "acc2"} <= set(logic.write_only_global_wires), list(
        logic.write_only_global_wires
    )
    print("test_unpack_into_wire_writes_it_in_sim PASS")


if __name__ == "__main__":
    test_sim_rejects_local_binding_of_wire_name()
    test_elab_rejects_local_binding_of_wire_name()
    test_elab_rejects_through_parse_file()
    test_module_alias_binding_rejected()
    test_sub_file_prefix_binding_rejected()
    test_other_module_local_is_not_the_wire()
    test_same_module_write_still_drives_wire()
    test_unpack_into_wire_writes_it_in_sim()
    print("All local_binds_global_wire tests passed.")
