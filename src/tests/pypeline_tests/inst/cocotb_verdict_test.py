# pyright: reportInvalidTypeForm=none
"""Regression guard for src/COCOTB.py's PASS/FAIL reporting.

Before the fix this guards, EVERY `--cocotb --ghdl --run all` simulation
reported a FAIL in cocotb's own console summary regardless of whether the
design actually passed -- sim_finish()'s std.env.finish terminates GHDL out
from under cocotb's still-running coroutine, and cocotb scored that a
SimFailure no matter what. src/COCOTB.py compensated by telling cocotb to
expect that specific SimFailure for --run all (expect_error=SimFailure) and
switched its verdict from log-text regex scraping to cocotb's own
results.xml. The two checks below are the direct regression guard for both
halves: a clean sim reports PASS (not the old universal FAIL), and a real
failure (a firing sim_assert) still reports FAIL -- i.e. the fix didn't
turn CHECK_COCOTB_RESULTS into a rubber stamp.

Run standalone: python3 cocotb_verdict_test.py
"""

import argparse
import os
import subprocess
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(THIS_DIR, "..", "..", "..", "pypelinec")
PASSING_DESIGN = os.path.join(THIS_DIR, "self_check_counter_test.py")
FAILING_DESIGN = os.path.join(THIS_DIR, "deliberate_sim_assert_failure_design.py")


def _run(design, out_dir):
    cmd = [
        sys.executable, PYPELINEC, design,
        "--sim", "--comb", "--cocotb", "--ghdl", "--run", "all",
        "--out_dir", out_dir,
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return result.stdout, result.returncode


def fail(msg):
    print(f"FAIL: {msg}")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()
    out_dir = args.out_dir or os.path.join(THIS_DIR, "cocotb_verdict_test_out")

    pass_out, pass_rc = _run(PASSING_DESIGN, os.path.join(out_dir, "pass"))
    print(pass_out)
    if pass_rc != 0:
        fail(f"expected exit 0 for a passing design ({PASSING_DESIGN}), got {pass_rc}")
    if "TESTS=1 PASS=1 FAIL=0" not in pass_out:
        fail(
            "expected cocotb's own summary to report a clean pass -- didn't find "
            "'TESTS=1 PASS=1 FAIL=0' in output above"
        )
    if "PASS: cocotb reported no test failures." not in pass_out:
        fail("expected COCOTB.py's verdict banner in output above, not found")

    fail_out, fail_rc = _run(FAILING_DESIGN, os.path.join(out_dir, "fail"))
    print(fail_out)
    if fail_rc == 0:
        fail(
            f"expected a nonzero exit for a design with a firing sim_assert "
            f"({FAILING_DESIGN}), got 0"
        )

    print("PASS: cocotb verdict reporting correctly distinguishes pass from fail.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
