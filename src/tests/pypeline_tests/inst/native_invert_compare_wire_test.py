"""Known-issue reproducers of issue #392: native simulation stores a global
wire's value as written, not cast to the wire's type.

- `~q`, where q is a Wire[uint1_t] written from a comparison (`q = t >= 2`),
  is truthy in every cycle: the wire holds a Python bool, and `~True` is -2.
  In hardware `~q` is the one-bit NOT, so from cycle 2 on the design prints "q".
- A list of plain ints written to a Wire[uint8_t[2]] stays plain ints, so
  array_to_uint_le packs each element at its own bit length: [1, 2] packs to
  5, where GHDL gives 0x0201 = 513.

Each runs its design natively and asserts the hardware's answer; they fail
while the bug is present (known_issues_tests.py, expect_fail).
"""

import os
import subprocess
import sys
import tempfile

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")

DESIGN = """
import sys
sys.path.insert(0, {src!r})
from pypeline import *

q: Wire[uint1_t]

@MAIN
def a():
    t: Reg[uint8_t]
    q = t >= 2
    t = t + 1

@MAIN
def b():
    if ~q:
        sim_print("not q")
    else:
        sim_print("q")
"""


PACK_DESIGN = """
import sys
sys.path.insert(0, {src!r})
from pypeline import *

lanes_w: Wire[uint8_t[2]]
packed: Output[uint16_t]

@MAIN(10.0)
def writer():
    lanes_w = [1, 2]

@MAIN(10.0)
def reader():
    packed = array_to_uint_le(lanes_w)
    sim_print(f"packed={{packed}}")
"""


def _native_run(design, cycles):
    """The stdout of a native run of design for cycles cycles."""
    with tempfile.TemporaryDirectory(prefix="native_invert_compare_wire_") as tmpdir:
        path = os.path.join(tmpdir, "design.py")
        with open(path, "w") as f:
            f.write(design.format(src=os.path.abspath(SRC)))
        proc = subprocess.run(
            [sys.executable, os.path.join(SRC, "pypeline_sim.py"), path, "--run", cycles],
            capture_output=True,
            text=True,
        )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout


def test_invert_of_comparison_wire():
    lines = [l for l in _native_run(DESIGN, "4").splitlines() if l in ("q", "not q")]
    assert lines == ["not q", "not q", "q", "q"], lines


def test_packing_a_list_written_to_an_array_wire():
    lines = [l for l in _native_run(PACK_DESIGN, "2").splitlines() if l.startswith("packed=")]
    assert lines == ["packed=513", "packed=513"], lines


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
