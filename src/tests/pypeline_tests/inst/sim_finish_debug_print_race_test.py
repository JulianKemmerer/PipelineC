# pyright: reportInvalidTypeForm=none
"""KNOWN ISSUE (reproducer, not a fix), two-in-one:

1. A sim_print(..., debug=True) call on the SAME cycle as sim_finish() races
   GHDL's write-flush against std.env.finish and reports a false failure --
   "Simulator shutdown prematurely" in cocotb's own regression summary --
   even though nothing is actually wrong with the design or the print.
   Native sim is unaffected (it always finishes cleanly). This is exactly
   the constraint documented at docs/pypeline_sim_DESIGN.md's Limitations
   section ("no debug=True prints on the sim_finish() cycle") and followed by
   every design in native_vs_vhdl_sim_tests.py (each delays its last print by
   a cycle from its sim_finish() call, or gates it out entirely -- see e.g.
   self_check_counter_test.py). This file demonstrates what happens if that
   rule is broken.

2. MORE SURPRISING: `pypelinec <this file> --sim --comb --cocotb --ghdl`
   exits 0 despite cocotb's own regression summary printing
   "TESTS=1 PASS=0 FAIL=1" and "Simulator shutdown prematurely" -- the
   cocotb-level failure does NOT propagate to pypelinec's process exit code
   in this race. That means run_all.py-style "exit code is the entire
   verdict" checking (native_vs_vhdl_sim/elab/synth) would silently call
   this a PASS. pypeline_sim_debug.py's own returncode check (added
   alongside this file) doesn't catch it either, for the same reason -- it
   trusts the same exit code. Hence this test is a WRAPPER (like
   build_report_tests.py's) that asserts on cocotb's own log text instead of
   trusting the exit code -- and its own "PASS" means "the known issue still
   reproduces": a run_all.py FAIL here is the signal to re-investigate,
   exactly like an XPASS elsewhere in this category. See
   known_issues_tests.py's registration comment for exactly this reasoning.

Whether this is a real GHDL/cocotb bug (VPI callback ordering vs
std.env.finish, and/or cocotb-result-to-exit-code plumbing) or an inherent
property of the two-process handshake is not established here -- it is filed
as a known issue because it constrains what test authors can write and what
run_all.py can trust, not because a fix has been identified.

See also: nested_truncate_vhdl_mismatch_known_issue.py, which works around
issue #1 with a one-cycle sim_finish() delay.
"""

import os
import subprocess
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(THIS_DIR, "..", "..", "..", "pypelinec")
DESIGN = os.path.join(THIS_DIR, "sim_finish_debug_print_race_design.py")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()

    cmd = [sys.executable, PYPELINEC, DESIGN, "--sim", "--comb", "--cocotb", "--ghdl", "--run", "all"]
    if args.out_dir:
        cmd += ["--out_dir", args.out_dir]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    out = result.stdout
    print(out)

    if "Simulator shutdown prematurely" not in out:
        print(
            "FAIL (issue appears RESOLVED): expected the same-cycle "
            "sim_print(debug=True)+sim_finish() race to trip cocotb's "
            "'Simulator shutdown prematurely' failure, but it did not -- "
            "promote this out of known_issues if confirmed."
        )
        return 1
    if result.returncode == 0:
        print(
            "NOTE: pypelinec exited 0 despite the cocotb-reported failure above "
            "-- reproducing known issue #2 (exit code does not reflect the "
            "cocotb race). This is the expected (still-broken) state."
        )
    print("PASS (known issue still reproduces, as expected).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
