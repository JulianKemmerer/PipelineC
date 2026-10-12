"""Known issue: AUTO_PIPELINE(func, latency=N) plans N register cuts in func's
own logic even when func's @pipeline_latency calls already supply the N cycles.

ENFORCE_AUTO_PIPELINE_REGIONS gives a fixed region "latency=N: N, always" cuts.
After lowering it verifies only the realized total latency. Cuts that would
lengthen the critical path fail that check and are retried with fewer. Cuts in a
branch parallel to the fixed-latency calls add no latency, so they stay. That
branch gets registers it does not need. Anything that leaves it before the
return value moves later: a VOLATILE or C global write, or a global read by a
function called there.

fixed_auto_pipeline_extra_cuts_design.py: core = two delay_one calls
(@pipeline_latency(1)) in parallel with `x + 1`, under AUTO_PIPELINE(core,
latency=2). This builds it (--comb --no_synth) and checks the adder the built
core instantiates:
  exit 0  combinational adder (0CLK): fixed
  exit 1  pipelined adder (NCLK, N > 0): the bug
  exit 2  the build or the VHDL scan failed (not this bug)
Registered in known_issues_tests.py (expect_fail).

Run standalone: python3 fixed_auto_pipeline_extra_cuts_test.py
"""

import argparse
import os
import re
import subprocess
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(THIS_DIR, "..", "..", "..", "pypelinec")
DESIGN = os.path.join(THIS_DIR, "fixed_auto_pipeline_extra_cuts_design.py")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()
    out_dir = args.out_dir or os.path.join(THIS_DIR, "fixed_auto_pipeline_extra_cuts_test_out")

    result = subprocess.run(
        [sys.executable, PYPELINEC, DESIGN, "--comb", "--no_synth", "--out_dir", out_dir],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(f"ERROR: build failed (exit {result.returncode}), not the known issue")
        return 2
    with open(os.path.join(out_dir, "vhdl_files.txt")) as f:
        cores = [p for p in f.read().split() if os.path.basename(p).startswith("core_")]
    if len(cores) != 1:
        print(f"ERROR: expected one built core entity, found {cores}")
        return 2
    with open(cores[0]) as f:
        adders = re.findall(r"entity work\.(BIN_OP_PLUS_\w+?_(\d+)CLK_\w+)", f.read())
    if not adders:
        print(f"ERROR: no adder instance in {cores[0]}")
        return 2
    piped = [name for name, clks in adders if int(clks) > 0]
    if piped:
        print(f"FAIL (known issue): {os.path.basename(cores[0])} instantiates {piped}")
        return 1
    print(f"PASS: {os.path.basename(cores[0])} adds no cuts beyond its @pipeline_latency calls")
    return 0


if __name__ == "__main__":
    sys.exit(main())
