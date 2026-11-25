"""A sim_print on the cycle a sim_assert fails appears in VHDL simulation
output, as it does in native simulation, and the assertion's message prints
the values of that cycle.

An assert of severity failure stops GHDL inside the delta cycle that runs it,
so asserting from the clocked process dropped any print process GHDL had not
yet run at that clock edge: "c=3" was missing from the cocotb + GHDL log. The
assertion now fires from a postponed process, after every process of the
time step, and prints copies of its arguments taken at the clock edge: by
then the register behind `c` holds 4, so an uncopied argument would print
"c reached 4".

Both runs fail on the assertion, so neither exit code shows the bug. This
wrapper runs both and exits 0 only when native simulation printed "c=1" to
"c=3" and failed with "c reached 3", and GHDL printed the same lines and
failed with the same message. Registered in build_report_tests.py.
"""

import argparse
import os
import subprocess
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(THIS_DIR, "..", "..", "..", "pypelinec")
DESIGN = os.path.join(THIS_DIR, "sim_assert_fail_print_design.py")
PRINTS = ["c=1", "c=2", "c=3"]
MESSAGE = "c reached 3"


def _run(extra_args, out_dir):
    cmd = [sys.executable, PYPELINEC, DESIGN] + extra_args + ["--out_dir", out_dir]
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    return result.stdout, result.returncode


def _problems(label, out, rc):
    """What is missing from one run's output, as a list of sentences."""
    lines = [line.strip() for line in out.splitlines()]
    problems = []
    if rc == 0:
        problems.append(f"{label} exited 0; expected the assertion to fail it.")
    missing = [p for p in PRINTS if p not in lines]
    if missing:
        problems.append(f"{label} did not print {missing}.")
    if "c=4" in lines:
        problems.append(f"{label} printed c=4, after the failing cycle.")
    if MESSAGE not in out:
        problems.append(f"{label} did not report '{MESSAGE}'.")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", required=True)
    args = parser.parse_args()

    native_out, native_rc = _run(
        ["--sim", "--comb", "--run", "all"], os.path.join(args.out_dir, "native")
    )
    vhdl_out, vhdl_rc = _run(
        ["--sim", "--comb", "--cocotb", "--ghdl", "--run", "all"],
        os.path.join(args.out_dir, "vhdl"),
    )
    print(native_out)
    print(vhdl_out)

    problems = _problems("native simulation", native_out, native_rc)
    problems += _problems("cocotb + GHDL", vhdl_out, vhdl_rc)
    for problem in problems:
        print("FAIL:", problem)
    if problems:
        return 1
    print(
        "PASS: both simulations printed the failing cycle's line and failed "
        "with its values."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
