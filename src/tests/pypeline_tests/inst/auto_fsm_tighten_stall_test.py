#!/usr/bin/env python3
"""AUTO_FSM tighten-loop termination: when rescheduling cannot move the
critical path, the driver must stop promptly and say why.

auto_fsm_tighten_test.py under sky130 measures 102.25 MHz at every schedule
(2, 3 and 6 states): its critical path is the FSM's input-capture enable,
one gate fanning out to all 142 input-register bits, which no state count
changes. Built at 110 MHz from a loose --auto_fsm_budget_scale 1.5, the driver
used to tighten pass after pass until the budget fell below one adder, the
adds decomposed into gates, a combinational candidate whose never-measured
gates were priced at 0 won as a "0 ops -> 0 shared unit(s)" schedule, and
codegen ran for 30+ minutes rendering it as inline glue.

Asserted below: the first tightened build shows no fmax gain, so the driver
prints its stall message and stops there (two schedule passes, no pass after
the message), never prints a 0-op schedule, reports the unmet goal with a
nonzero exit, and finishes inside the subprocess timeout.
"""
import argparse
import os
import re
import subprocess
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_SRC = os.path.abspath(os.path.join(THIS_DIR, "..", "..", ".."))
PYPELINEC = os.path.join(REPO_SRC, "pypelinec")
DESIGN = os.path.join(THIS_DIR, "..", "auto_fsm_tighten_test.py")
GOAL_MHZ = "110.0"  # above the ~102 MHz this design reaches at any schedule
START_BUDGET_SCALE = "1.5"
TIMEOUT_S = 20 * 60
STALL_TEXT = "AUTO_FSM: tightening changed the schedule"


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def patched_design(out_dir):
    """The shared fixture at GOAL_MHZ instead of its PyRTL-tuned 40 MHz,
    written beside the build (its repo-relative sys.path line is pinned to
    an absolute path, since the copy lives elsewhere)."""
    with open(DESIGN) as f:
        src = f.read()
    replacements = (
        ("@MAIN(40.0)", f"@MAIN({GOAL_MHZ})"),
        (
            'os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")',
            repr(REPO_SRC),
        ),
    )
    for old, new in replacements:
        if src.count(old) != 1:
            fail(f"fixture changed: expected exactly one {old!r} in {DESIGN}")
        src = src.replace(old, new)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "auto_fsm_tighten_stall_design.py")
    with open(path, "w") as f:
        f.write(src)
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()

    out_dir = args.out_dir or os.path.join(THIS_DIR, "auto_fsm_tighten_stall_test_out")
    design = patched_design(out_dir)
    cmd = [
        sys.executable,
        PYPELINEC,
        design,
        "--syn_tool",
        "device_models",
        "--out_dir",
        os.path.join(out_dir, "build"),
        "--auto_fsm_budget_scale",
        START_BUDGET_SCALE,
    ]
    print("Running:", " ".join(cmd), flush=True)
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as e:
        out = e.stdout or ""
        if isinstance(out, bytes):
            out = out.decode(errors="replace")
        print(out)
        fail(
            f"build still running after {TIMEOUT_S}s -- the AUTO_FSM tighten "
            f"loop did not stop when rescheduling stopped helping"
        )
    out = result.stdout
    print(out)

    if re.search(r"^AUTO_FSM \S+: 0 ops -> ", out, re.M):
        fail(
            "a 0-op schedule was produced -- unmeasured operations were priced "
            "as free wiring"
        )
    if STALL_TEXT not in out:
        fail("the driver never reported that tightening stopped improving fmax")
    after_stall = out.split(STALL_TEXT, 1)[1]
    if re.search(r"^=+ AUTO_FSM Pass \d+: ", after_stall, re.M):
        fail("the driver kept scheduling after reporting the stall")
    passes = re.findall(r"^=+ AUTO_FSM Pass (\d+): ", out, re.M)
    if len(passes) != 2:
        fail(
            f"expected exactly 2 schedule passes (first build, one tightened "
            f"build that shows no gain), got {len(passes)}"
        )
    checks = re.findall(
        r"^\[sweep\] \S+ synthesized as written \(standalone check\): "
        r"([\d.]+) MHz vs ([\d.]+) MHz goal - (PASS|FAIL)",
        out,
        re.M,
    )
    if len(checks) != 2 or any(c[2] != "FAIL" for c in checks):
        fail(
            f"expected two failing timing checks (this goal is unreachable), "
            f"got {checks!r} -- if the delay model moved, retune GOAL_MHZ"
        )
    if result.returncode == 0:
        fail("the build met no goal yet exited 0")

    print(
        f"AUTO_FSM tighten-stall test passed: {checks[0][0]} -> {checks[1][0]} "
        f"MHz vs a {GOAL_MHZ} MHz goal, stopped after {len(passes)} passes "
        f"(exit {result.returncode})."
    )


if __name__ == "__main__":
    main()
