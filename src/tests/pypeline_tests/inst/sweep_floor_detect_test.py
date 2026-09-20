#!/usr/bin/env python3
# Planned throughput sweep test (e): fmax floor detection.
# Runs pypelinec on sweep_floor_detect_design.py (whose goal is unreachable -
# a divider is trapped inside a stateful submodule) and asserts:
#  - the sweep predicts and reports the fmax floor BEFORE any synthesis runs
#  - it stops after only a few full-design synthesis runs instead of blindly
#    growing the cut count, with the expected stop reason in
#    sweep_history.json (never iteration_limit)
#  - the build FAILS with a non zero exit + TIMING NOT MET error block
#    (results still written for debugging first)
#
# --syn_tool picks the stop path under test (see the design's header):
#  sky130 (100 MHz goal): the measured plateau sits far above the soft-floor
#    prediction, so the prediction-independent "plateau" stop ends the sweep
#  pyrtl (50 MHz goal): the prediction matches, so "empirical_floor" does
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(THIS_DIR, "../../../pypelinec")
DESIGN = os.path.join(THIS_DIR, "sweep_floor_detect_design.py")
MAIN_NAME = "sweep_floor_main"

# tool -> (goal MHz, expected stopped_reason, expected stop warning text)
TOOLS = {
    "device_models": (100.0, "plateau", "fmax plateaued at"),
    "pyrtl": (50.0, "empirical_floor", "at empirical (soft) fmax floor"),
}

# Bound the complete search, including the measured-delay fallback for the
# hierarchical soft comparator and the one permitted chunked-MUX refinement.
# Measured sky130 history: fallback at run 2, MUX probe at run 4, final plateau
# at run 7. These bounded probes must not become unbounded global densification.
MAX_FULL_SYN_RUNS = 7


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    parser.add_argument("--syn_tool", choices=sorted(TOOLS), default="device_models")
    args = parser.parse_args()
    goal_mhz, want_reason, want_warning = TOOLS[args.syn_tool]
    out_dir = args.out_dir or tempfile.mkdtemp(prefix="sweep_floor_detect_")

    cmd = [
        sys.executable,
        PYPELINEC,
        DESIGN,
        "--syn_tool",
        args.syn_tool,
        "--out_dir",
        out_dir,
    ]
    env = dict(os.environ, SWEEP_FLOOR_DETECT_MHZ=str(goal_mhz))
    print(f"Running (goal {goal_mhz} MHz):", " ".join(cmd), flush=True)
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env
    )
    out = result.stdout
    print(out)

    # Timing is NOT met by design here: the build must FAIL (non zero exit)
    # so users cannot miss it - but only after writing results for debugging
    if result.returncode == 0:
        print("FAIL: pypelinec exited zero despite unmet timing goal")
        sys.exit(1)
    if "ERROR: TIMING NOT MET" not in out:
        print("FAIL: no TIMING NOT MET error block")
        sys.exit(1)
    if "Writing Results of Throughput Sweep" not in out:
        print("FAIL: results were not written before failing")
        sys.exit(1)
    if "predicted fmax floor" not in out:
        print("FAIL: no predicted fmax floor report before synthesis")
        sys.exit(1)
    if "below the" not in out or "goal" not in out:
        print("FAIL: no warning that the floor is below the timing goal")
        sys.exit(1)
    if want_warning not in out:
        print(f"FAIL: no '{want_warning}' stop warning")
        sys.exit(1)
    full_syn_runs = len(re.findall(r"Running syn w timing params", out))
    if full_syn_runs > MAX_FULL_SYN_RUNS:
        print(
            f"FAIL: {full_syn_runs} full design synthesis runs (max {MAX_FULL_SYN_RUNS}) - floor detection should stop the sweep quickly"
        )
        sys.exit(1)
    history_path = os.path.join(out_dir, "top", "sweep_history.json")
    with open(history_path) as f:
        final = json.load(f)["mains"][MAIN_NAME]["final"]
    reason = final.get("stopped_reason")
    if reason != want_reason:
        print(
            f"FAIL: {history_path} final stopped_reason is {reason!r}, "
            f"expected {want_reason!r}"
        )
        sys.exit(1)
    if final.get("met") is not False:
        print(f"FAIL: {history_path} final verdict is not a failure: {final}")
        sys.exit(1)
    print(
        f"All sweep floor detect tests passed ({args.syn_tool}: {reason}, "
        f"{full_syn_runs} full syn runs)."
    )


if __name__ == "__main__":
    main()
