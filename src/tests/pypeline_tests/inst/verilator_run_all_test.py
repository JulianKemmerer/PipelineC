"""Known issue: `pypelinec --sim --comb --verilator --run all` crashes, and
the Verilator model ignores sim_finish().

VERILATOR.DO_SIM compares `args.run <= 0`, and `--run all` makes args.run the
string "all", so the run stops with a TypeError before Verilator builds. The
GHDL/Yosys conversion to Verilog also drops sim_finish(), as it drops
sim_print: with `--run 8`, verilator_run_all_design.py runs all 8 cycles,
although it calls sim_finish() in cycle 4.

This test runs verilator_run_all_design.py with `--run all` and passes when
the run exits 0 and stops by cycle 5, the cycle after sim_finish(). It reads
the cycle numbers from the default main.cpp's "cycle N:" lines. Registered in
known_issues_tests.py (expect_fail, needs GHDL, Yosys and Verilator, about
40 s): it fails while the crash is present.
"""

import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(HERE, "..", "..", "..", "pypelinec")


def test_verilator_run_all_stops_at_sim_finish():
    design = os.path.join(HERE, "verilator_run_all_design.py")
    with tempfile.TemporaryDirectory(prefix="verilator_run_all_") as out_dir:
        result = subprocess.run(
            [sys.executable, PYPELINEC, design, "--sim", "--comb", "--verilator",
             "--run", "all", "--out_dir", out_dir],
            capture_output=True,
            text=True,
        )
    output = result.stdout + result.stderr
    print(output[-3000:])
    assert result.returncode == 0, f"--verilator --run all exited {result.returncode}"
    cycles = [int(n) for n in re.findall(r"^cycle (\d+):", output, re.MULTILINE)]
    assert cycles, "no 'cycle N:' lines: update this test to the new driver's output"
    assert max(cycles) <= 5, f"ran to cycle {max(cycles)}: sim_finish() in cycle 4 was ignored"
    print("PASS: --verilator --run all stopped at sim_finish()")


if __name__ == "__main__":
    test_verilator_run_all_stops_at_sim_finish()
