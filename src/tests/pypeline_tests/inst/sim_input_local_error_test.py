# pyright: reportInvalidTypeForm=none
"""A @sim_input/@sim_output value reaches hardware only through a module-level wire.

`x = stim()` with `x` a LOCAL used to make HDL elaboration RUN the @sim_input
(its constant-folding evaluated the call as plain Python) and build the value
into hardware: a scalar silently became a constant (`return x + 1` -> 43), a
struct failed with "Cannot emit non-int Python value as hardware". A pipelined
(non---comb) --sim elaborates the testbench top before simulating it, so such a
testbench synthesized the wrong circuit.

Now:
- native sim rejects every statically visible misuse at decoration time
  (pypeline.SimOnlyCallSiteError): a local target, an annotated local, a field
  of a local, an unpacking target, a sim-only call nested in an expression;
- elaboration rejects the same set (PY_TO_LOGIC.ElaborationError), and never
  executes a sim-only body -- including one hidden inside a plain-Python helper,
  which only elaboration can see;
- the sanctioned forms still work: a bare call statement, and a whole-RHS call
  assigned to a module-level wire (bare, a field of one, or `module.wire.field`
  through an imported module -- WireGuard's testbench shape).

Design modules are written to a temp dir and imported per case, since the sim
error fires at import (decoration) time. Elaboration's own check is reached by
stubbing the sim check out (local_binds_global_wire_test.py's pattern).
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

TMP = tempfile.mkdtemp(prefix="sim_input_local_error_")
sys.path.insert(0, TMP)
SYN.SYN_OUTPUT_DIRECTORY = os.path.join(TMP, "syn_out")
_counter = itertools.count()

# Every sim-only body appends its name to MARKER, so a test can prove
# elaboration never ran one.
HEADER = """\
# pyright: reportInvalidTypeForm=none
from typing import NamedTuple
from pypeline import MAIN, Input, Wire, hw_func, sim_input, sim_output, struct, uint8_t

MARKER = {marker!r}


@struct
class pair_t(NamedTuple):
    a: uint8_t
    b: uint8_t


@sim_input
def stim() -> uint8_t:
    open(MARKER, "a").write("stim\\n")
    return 42


@sim_input
def stim_pair() -> pair_t:
    open(MARKER, "a").write("stim_pair\\n")
    return pair_t(a=1, b=2)


@sim_output
def chk(v):
    open(MARKER, "a").write("chk\\n")


def helper():
    return stim()


@hw_func
def g(v: uint8_t) -> uint8_t:
    return v + 1

"""

# Module declaring a compound wire, imported under an alias by the
# `module.wire.field = stim()` case.
PORTS = """\
# pyright: reportInvalidTypeForm=none
from typing import NamedTuple
from pypeline import Wire, struct, uint8_t


@struct
class port_pair_t(NamedTuple):
    a: uint8_t
    b: uint8_t


pw: Wire[port_pair_t]
"""


def _fresh(prefix):
    return f"{prefix}_{next(_counter)}"


def _write(name, body):
    path = os.path.join(TMP, f"{name}.py")
    marker = os.path.join(TMP, f"{name}.marker")
    with open(path, "w") as fh:
        fh.write(HEADER.format(marker=marker) + textwrap.dedent(body))
    return path, marker


def _import(name):
    importlib.invalidate_caches()  # the module file was just written
    return importlib.import_module(name)


def _ran(marker):
    if not os.path.exists(marker):
        return []
    with open(marker) as fh:
        return fh.read().split()


class _sim_check_disabled:
    """Import a design whose sim-side check would raise, so elaboration's own
    check can be exercised."""

    def __enter__(self):
        self._saved = pypeline._check_sim_only_call_sites
        pypeline._check_sim_only_call_sites = lambda *a, **k: None

    def __exit__(self, *exc):
        pypeline._check_sim_only_call_sites = self._saved


# label -> (MAIN body, callee name the errors must mention, statically visible?)
MISUSE_CASES = {
    "scalar local (handoff repro)": (
        """
        @MAIN
        def top() -> uint8_t:
            x = stim()
            return x + 1
        """,
        "stim",
        True,
    ),
    "struct local": (
        """
        @MAIN
        def top() -> uint8_t:
            p = stim_pair()
            return p.a + p.b
        """,
        "stim_pair",
        True,
    ),
    "annotated local": (
        """
        @MAIN
        def top() -> uint8_t:
            x: uint8_t = stim()
            return x
        """,
        "stim",
        True,
    ),
    "field of a local": (
        """
        @MAIN
        def top(v: uint8_t) -> uint8_t:
            p = pair_t(a=v, b=v)
            p.a = stim()
            return p.a
        """,
        "stim",
        True,
    ),
    "unpacking target": (
        """
        @MAIN
        def top() -> uint8_t:
            a, b = stim_pair()
            return a + b
        """,
        "stim_pair",
        True,
    ),
    "nested in an expression": (
        """
        @MAIN
        def top() -> uint8_t:
            return stim() + 1
        """,
        "stim",
        True,
    ),
    "hw_func argument": (
        """
        @MAIN
        def top() -> uint8_t:
            return g(stim())
        """,
        "stim",
        True,
    ),
    "@sim_output result in a local": (
        """
        @MAIN
        def top(v: uint8_t) -> uint8_t:
            x = chk(1)
            return v
        """,
        "chk",
        True,
    ),
    "hidden inside a plain-Python helper": (
        """
        @MAIN
        def top() -> uint8_t:
            x = helper()
            return x + 1
        """,
        "stim",
        False,
    ),
}


def test_sim_rejects_misuse():
    for label, (body, callee, static) in MISUSE_CASES.items():
        name = _fresh("misuse_sim")
        _, marker = _write(name, body)
        try:
            _import(name)
        except pypeline.SimOnlyCallSiteError as e:
            assert static, f"{label}: not statically visible, yet sim rejected: {e}"
            msg = str(e)
            assert f"'{callee}()'" in msg, (label, msg)
            assert "Input[" in msg, (label, msg)
            assert f"{name}.py:" in msg, (label, msg)
        else:
            assert not static, f"sim accepted {label}"
        assert _ran(marker) == [], (label, _ran(marker))
    print("test_sim_rejects_misuse PASS")


def test_elab_rejects_misuse_without_running_it():
    for label, (body, callee, _static) in MISUSE_CASES.items():
        name = _fresh("misuse_elab")
        _, marker = _write(name, body)
        with _sim_check_disabled():
            mod = _import(name)
        try:
            py.ELABORATE_LIVE_ROOTS([mod.top])
        except py.ElaborationError as e:
            msg = str(e.args[0])
            assert f"'{callee}()'" in msg, (label, msg)
            assert "Input[" in msg, (label, msg)
        else:
            raise AssertionError(f"elaboration accepted {label}")
        assert _ran(marker) == [], f"{label}: elaboration ran {_ran(marker)}"
    print("test_elab_rejects_misuse_without_running_it PASS")


def test_parse_file_rejects_handoff_repro():
    """The pypelinec path: PARSE_FILE elaborates the testbench top."""
    name = _fresh("repro_parse")
    path, marker = _write(name, MISUSE_CASES["scalar local (handoff repro)"][0])
    try:
        py.PARSE_FILE(path)
    except pypeline.SimOnlyCallSiteError as e:
        assert "'x'" in str(e), e
    else:
        raise AssertionError("PARSE_FILE imported a design capturing stim() in a local")
    with _sim_check_disabled():
        try:
            py.PARSE_FILE(path)
        except py.ElaborationError as e:
            msg = str(e.args[0])
            assert "'x'" in msg and "'stim()'" in msg, msg
        else:
            raise AssertionError("PARSE_FILE elaborated stim() into a local")
    assert _ran(marker) == [], _ran(marker)
    print("test_parse_file_rejects_handoff_repro PASS")


def test_sanctioned_forms_still_work():
    ports = _fresh("simin_ports")
    with open(os.path.join(TMP, f"{ports}.py"), "w") as fh:
        fh.write(PORTS)
    name = _fresh("sanctioned")
    path, marker = _write(
        name,
        f"""
        import {ports} as ports

        in0: Input[uint8_t]
        pw: Wire[pair_t]


        # As in WireGuard's testbenches, hardware drives the other field of
        # each wire: a sim-only write is no hardware writer at all.
        @MAIN
        def top() -> uint8_t:
            in0 = stim()             # whole wire
            pw.a = stim()            # field of a module wire
            pw.b = in0
            ports.pw.a = stim()      # module.wire.field (WireGuard's shape)
            ports.pw.b = in0
            chk(in0)                 # bare statement
            return in0 + 1
        """,
    )
    mod = _import(name)  # the sim check accepts every form
    pypeline.sim_reset()
    assert int(pypeline.sim_call(mod.top)) == 43
    assert "stim" in _ran(marker), _ran(marker)

    os.remove(marker)
    py.PARSE_FILE(path)  # elaboration accepts them too, without running any
    assert _ran(marker) == [], _ran(marker)
    print("test_sanctioned_forms_still_work PASS")


if __name__ == "__main__":
    test_sim_rejects_misuse()
    test_elab_rejects_misuse_without_running_it()
    test_parse_file_rejects_handoff_repro()
    test_sanctioned_forms_still_work()
    print("All sim_input_local_error tests passed.")
