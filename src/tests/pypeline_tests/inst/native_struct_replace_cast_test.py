"""Known issue: in native simulation a struct value built with
NamedTuple._replace() or _make() keeps the Python values it was given, where
the same value built with the struct's constructor has its fields typed.

The struct below has a uint8_t field and a uint8_t[2] field, so the hardware
holds 300 as 44 (300 mod 256) and packs the lanes [1, 2] to 0x0201 = 513.
Built as pair_t(a=300, lanes=[1, 2]) native simulation agrees; built with
_replace or _make it keeps 300 and packs [1, 2] at the elements' own bit
lengths, 5. Each test asserts the hardware's answer for one place such a
value can land: a whole-wire write, a typed local and a Reg.

Elaboration rejects `_replace` inside a hardware function, so this reaches
only code that runs in native simulation alone (sim-only MAINs, @sim_input
functions, testbench helpers). Registered in known_issues_tests.py with
expect_fail=True: the module exits nonzero while the bug is present (XFAIL).
"""

import functools
import os
import subprocess
import sys
import tempfile

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")

DESIGN = """
import sys
from typing import NamedTuple
sys.path.insert(0, {src!r})
from pypeline import *

@struct
class pair_t(NamedTuple):
    a: uint8_t
    lanes: uint8_t[2]

BASE = pair_t(a=1, lanes=[0, 0])

w_replace: Wire[pair_t]
w_make: Wire[pair_t]

@MAIN
def writer():
    w_replace = BASE._replace(a=300, lanes=[1, 2])
    w_make = pair_t._make([300, [1, 2]])

@MAIN
def reader():
    loc: pair_t = BASE._replace(a=300)
    r: Reg[pair_t]
    r = BASE._replace(a=300)
    sim_print(f"replace_a={{w_replace.a}}")
    sim_print(f"replace_packed={{array_to_uint_le(w_replace.lanes)}}")
    sim_print(f"make_a={{w_make.a}}")
    sim_print(f"local_a={{loc.a}}")
    sim_print(f"reg_a={{r.a}}")
"""


@functools.lru_cache(maxsize=None)
def _native_lines():
    """The stdout lines of a two-cycle native run of DESIGN."""
    with tempfile.TemporaryDirectory(prefix="native_struct_replace_cast_") as tmpdir:
        path = os.path.join(tmpdir, "design.py")
        with open(path, "w") as f:
            f.write(DESIGN.format(src=os.path.abspath(SRC)))
        proc = subprocess.run(
            [sys.executable, os.path.join(SRC, "pypeline_sim.py"), path, "--run", "2"],
            capture_output=True,
            text=True,
        )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return tuple(proc.stdout.splitlines())


def _printed(prefix):
    """The sim_print lines of the run that start with prefix."""
    return [l for l in _native_lines() if l.startswith(prefix)]


def test_replace_scalar_field_on_a_wire_holds_the_field_width():
    assert _printed("replace_a=") == ["replace_a=44"] * 2, _printed("replace_a=")


def test_replace_array_field_on_a_wire_packs_at_the_element_width():
    lines = _printed("replace_packed=")
    assert lines == ["replace_packed=513"] * 2, lines


def test_make_scalar_field_on_a_wire_holds_the_field_width():
    assert _printed("make_a=") == ["make_a=44"] * 2, _printed("make_a=")


def test_replace_scalar_field_in_a_typed_local_holds_the_field_width():
    assert _printed("local_a=") == ["local_a=44"] * 2, _printed("local_a=")


def test_replace_scalar_field_in_a_reg_holds_the_field_width():
    assert _printed("reg_a=") == ["reg_a=44"] * 2, _printed("reg_a=")


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
