#!/usr/bin/env python3
# Build-report regression test: a design that synthesizes away to nothing must
# FAIL the pipelined build, and say why.
#
# no_outputs_design.py is a single stateful goal-less @MAIN with no top-level
# outputs. It guards two fixes at once:
#  - it gets PAST the throughput sweep (a single stateful main with no target
#    MHz used to be forced into the coarse sweep and die with "Trying to slice
#    into ... for no reason"; see single_stateful_main_fixed_latency_test.py
#    for the passing, output-driving version);
#  - it then fails for the RIGHT reason. yosys optimizes the whole netlist
#    away; PyRTL's zero-FF-overhead max_freq used to divide by zero, and
#    PYRTL.PathReport then parsed the traceback's quoted
#    print("Fmax (MHz):", ...) source line into "could not convert string to
#    float". Now the generated script prints PYRTL.NO_TIMING_PATHS_MARKER and
#    the build raises a readable error. A circuit with no timing paths has no
#    Fmax: that must stay an error, never a skipped or passing measurement.
import os
import subprocess
import sys
import tempfile

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(THIS_DIR, "../../../pypelinec")
DESIGN = os.path.join(THIS_DIR, "no_outputs_design.py")


def main():
    parser = __import__("argparse").ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()
    out_dir = args.out_dir
    if out_dir is None:
        out_dir = tempfile.mkdtemp(prefix="pyrtl_no_timing_paths_build_report_test_")

    cmd = [
        sys.executable,
        PYPELINEC,
        DESIGN,
        "--syn_tool",
        "pyrtl",
        "--pipeline_min_effort",
        "0",
        "--out_dir",
        out_dir,
    ]
    print("Running:", " ".join(cmd), flush=True)
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    out = result.stdout
    print(out)

    failures = []
    if result.returncode == 0:
        failures.append("build of a design with no outputs SUCCEEDED; must fail")
    if "for no reason" in out:
        failures.append("single stateful goal-less main still forced into coarse slicing")
    if "no timing paths" not in out or "@wires" not in out:
        failures.append("missing the clear 'no timing paths ... @wires' error text")
    for confusing in ("could not convert string to float", "ZeroDivisionError"):
        if confusing in out:
            failures.append(f"confusing failure text still present: {confusing!r}")
    if failures:
        for f in failures:
            print("FAIL:", f)
        sys.exit(1)
    print("PASS: no-output design fails with the clear no-timing-paths error")


if __name__ == "__main__":
    main()
