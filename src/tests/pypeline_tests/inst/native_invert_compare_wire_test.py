"""Known-issue reproducer: native simulation of `~q`, where q is a
Wire[uint1_t] written from a comparison (`q = t >= 2`), is truthy in every
cycle: the wire holds a Python bool, and `~True` is -2. In hardware `~q` is
the one-bit NOT, so from cycle 2 on the design prints "q". This runs the
design natively and asserts the hardware's answer; it fails while the bug is
present (known_issues_tests.py, expect_fail).
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


def test_invert_of_comparison_wire():
    with tempfile.TemporaryDirectory(prefix="native_invert_compare_wire_") as tmpdir:
        path = os.path.join(tmpdir, "design.py")
        with open(path, "w") as f:
            f.write(DESIGN.format(src=os.path.abspath(SRC)))
        proc = subprocess.run(
            [sys.executable, os.path.join(SRC, "pypeline_sim.py"), path, "--run", "4"],
            capture_output=True,
            text=True,
        )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    lines = [l for l in proc.stdout.splitlines() if l in ("q", "not q")]
    assert lines == ["not q", "not q", "q", "q"], lines


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
