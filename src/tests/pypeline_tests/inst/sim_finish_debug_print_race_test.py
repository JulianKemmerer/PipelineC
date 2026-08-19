# pyright: reportInvalidTypeForm=none
"""KNOWN ISSUE (reproducer, not a fix): a sim_print(..., debug=True) call on
the SAME cycle as sim_finish() is silently DROPPED from the cocotb+GHDL log
entirely -- not printed late, not printed with a warning, just absent --
even though the identical design's native (Python) sim prints it normally.
Confirmed directly: sim_finish_debug_print_race_design.py's "about to finish"
line appears in native --sim --comb --run all output but not anywhere in its
--cocotb --ghdl --run all output, despite both runs exiting 0. The cause is
a process-ordering race between GHDL's VHDL write-flush for the print and
std.env.finish (from sim_finish()) killing the simulator on the same clock
edge -- exactly the constraint documented at docs/pypeline_sim_DESIGN.md's
Limitations section ("no debug=True prints on the sim_finish() cycle") and
followed by every design in native_vs_vhdl_sim_tests.py (each delays its
last print by a cycle from its sim_finish() call, or gates it out entirely
-- see e.g. self_check_counter_test.py). This file demonstrates what happens
if that rule is broken.

Earlier revisions of this test asserted on cocotb's own "Simulator shutdown
prematurely" scheduler message instead. That text turned out to appear in
EVERY --run all cocotb simulation, passing or failing (see src/COCOTB.py's
CHECK_COCOTB_RESULTS docstring) -- so it reproduced trivially and proved
nothing specific to this race. Once COCOTB.py started telling cocotb to
expect that shutdown (expect_error=SimFailure), the old assertion would have
started reproducing even on runs that break no rule at all. This revision
asserts on the real, still-present symptom instead: the missing print line.

Whether this is a real GHDL/cocotb bug (VPI callback ordering vs
std.env.finish) or an inherent property of the two-process handshake is not
established here -- it is filed as a known issue because it constrains what
test authors can write, not because a fix has been identified.

See also: nested_truncate_test.py (formerly nested_truncate_vhdl_mismatch_
known_issue.py, promoted out of known_issues once its own unrelated VHDL bug
was fixed), which works around this by delaying sim_finish() one cycle past
its design's own debug print.
"""

import os
import subprocess
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(THIS_DIR, "..", "..", "..", "pypelinec")
DESIGN = os.path.join(THIS_DIR, "sim_finish_debug_print_race_design.py")
PROBE_TEXT = "about to finish"


def _run(extra_args, out_dir):
    cmd = [sys.executable, PYPELINEC, DESIGN] + extra_args + ["--out_dir", out_dir]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return result.stdout, result.returncode


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()
    out_dir = args.out_dir or os.path.join(THIS_DIR, "sim_finish_debug_print_race_test_out")

    native_out, native_rc = _run(["--sim", "--comb", "--run", "all"], os.path.join(out_dir, "native"))
    vhdl_out, vhdl_rc = _run(
        ["--sim", "--comb", "--cocotb", "--ghdl", "--run", "all"], os.path.join(out_dir, "vhdl")
    )
    print(native_out)
    print(vhdl_out)

    if native_rc != 0:
        print(f"FAIL (harness broken): native sim exited {native_rc}, expected 0.")
        return 1
    if PROBE_TEXT not in native_out:
        print(f"FAIL (harness broken): native sim never printed {PROBE_TEXT!r} at all.")
        return 1
    if vhdl_rc != 0:
        print(
            f"NOTE: VHDL/cocotb sim exited {vhdl_rc} (nonzero) -- a stricter failure mode "
            f"than the known issue itself, but still consistent with 'the rule was broken'."
        )
    if PROBE_TEXT not in vhdl_out:
        print(
            "PASS (known issue still reproduces, as expected): native sim printed "
            f"{PROBE_TEXT!r} but the VHDL/cocotb sim never did."
        )
        return 0
    print(
        f"FAIL (issue appears RESOLVED): expected the same-cycle "
        f"sim_print(debug=True)+sim_finish() race to silently drop {PROBE_TEXT!r} from "
        f"the VHDL/cocotb log, but it printed normally -- promote this out of "
        f"known_issues if confirmed."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
