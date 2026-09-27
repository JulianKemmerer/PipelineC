#!/usr/bin/env python3
"""Real-build regression for recursively zero-delay generated helpers.

The wiring-only ``swap`` helper in zero_delay_helper_build_design.py contains
only generated CONST_REF_RD children. A delay walk can skip those children,
leaving ``delay=None``. Before the fix, classifying ``swap`` treated that as
unresolved timing, synthesized the wiring harness pointlessly, and the later
pipeline-map walk crashed with ``Can't get zero clock pipeline map without
delay?``.

Run the actual sky130 --comb build and require the fixed AUTO_PIPELINE region
to realize both requested registers, so this test covers the production path
rather than calling the classifier or pipeline-map helpers directly.
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(THIS_DIR, "../../../pypelinec")
DESIGN = os.path.join(THIS_DIR, "zero_delay_helper_build_design.py")


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()

    out_dir = args.out_dir
    if out_dir is None:
        out_dir = tempfile.mkdtemp(prefix="zero_delay_helper_build_test_")
    cmd = [
        sys.executable,
        PYPELINEC,
        DESIGN,
        "--comb",
        "--syn_tool",
        "device_models",
        "--out_dir",
        out_dir,
    ]
    print("Running:", " ".join(cmd), flush=True)
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    out = result.stdout
    print(out)

    if result.returncode != 0:
        fail(f"pypelinec exited nonzero ({result.returncode})")
    if "Can't get zero clock pipeline map without delay?" in out:
        fail("build hit the zero-delay pipeline-map regression")
    # The region label is derived from the design module name (for example
    # pypeline_design_core_latency_2), so match the core instance instead.
    if not re.search(
        r"^AUTO_PIPELINE \S+ \(latency=2\): 2 clk\(s\) built at \S*____core\[",
        out,
        re.M,
    ):
        fail("fixed-latency core did not report exactly 2 clk(s) built")

    print("Zero-delay helper build regression passed: core built at latency 2.")


if __name__ == "__main__":
    main()
