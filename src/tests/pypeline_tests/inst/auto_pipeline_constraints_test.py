#!/usr/bin/env python3
# AUTO_PIPELINE latency constraints end-to-end (full planned sweep, PyRTL):
#  (a) auto_pipeline_constraints_design.py -- latency=2 and start_latency=1
#      call sites are built with exactly 2 and 1 registers, and because the
#      design's .latency reads already equal what was built, the driver skips
#      the pin-and-confirm re-elaboration pass
#  (b) auto_pipeline_max_latency_design.py -- an unreachable goal whose only
#      pipelinable logic is capped at max_latency=1: at most 1 register is
#      built, the sweep stops promptly naming the cap, and the build fails
import argparse
import json
import os
import re
import subprocess
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(THIS_DIR, "../../../pypelinec")


def run(design, out_dir, extra=()):
    cmd = [sys.executable, PYPELINEC, os.path.join(THIS_DIR, design), "--syn_tool", "device_models"]
    if out_dir:
        cmd += ["--out_dir", out_dir]
    cmd += list(extra)
    print("Running:", " ".join(cmd), flush=True)
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    print(result.stdout)
    return result.returncode, result.stdout


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def harvested(out):
    return {
        key: int(clks)
        for key, clks in re.findall(r"^AUTO_PIPELINE (\S+): (\d+) clks$", out, re.M)
    }


def check_fixed_and_start(out_dir):
    rc, out = run(
        "auto_pipeline_constraints_design.py",
        out_dir,
        ["--pipeline_min_effort", "0"],
    )
    if rc != 0:
        fail(f"constraints design build exited {rc}")
    if "fixed .latency=2 start .latency=1" not in out:
        fail("bootstrap .latency reads were not latency=2 / start_latency=1")
    latencies = harvested(out)
    fixed = [v for k, v in latencies.items() if k.endswith("_latency_2") and "start" not in k]
    start = [v for k, v in latencies.items() if k.endswith("_start_latency_1")]
    if fixed != [2]:
        fail(f"fixed latency=2 call site harvested {fixed} ({latencies})")
    if start != [1]:
        fail(f"start_latency=1 call site harvested {start} ({latencies})")
    if "skipping pin-and-confirm pass 2" not in out:
        fail("pass 2 skip not taken although every .latency read matched")
    if "AUTO_PIPELINE Pass 2" in out:
        fail("pin-and-confirm pass 2 ran although it was not needed")
    region_lines = re.findall(r"^\[sweep\] AUTO_PIPELINE .*clk\(s\) built at", out, re.M)
    if len(region_lines) != 2:
        fail(f"expected 2 constrained region summary lines, got {region_lines}")
    if out_dir:
        history_path = os.path.join(out_dir, "top", "sweep_history.json")
        with open(history_path) as f:
            history = json.load(f)
        if "auto_pipeline_regions" not in json.dumps(history):
            fail(f"no auto_pipeline_regions entry in {history_path}")


def check_max_latency(out_dir):
    rc, out = run("auto_pipeline_max_latency_design.py", out_dir)
    if rc == 0:
        fail("unreachable goal behind max_latency=1 did not fail the build")
    if "limited by AUTO_PIPELINE latency constraint" not in out:
        fail("sweep did not name the max_latency cap as the limit")
    built = [
        int(n)
        for n in re.findall(
            r"^\[sweep\] AUTO_PIPELINE \S+ \(max_latency=1\): (\d+) clk\(s\) built",
            out,
            re.M,
        )
    ]
    if not built or max(built) > 1:
        fail(f"max_latency=1 region built {built} clks")
    iterations = [int(n) for n in re.findall(r"iterations=(\d+)", out)]
    if not iterations or max(iterations) >= 12:
        fail(f"sweep did not stop promptly at the cap (iterations={iterations})")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args()
    sub = (lambda name: os.path.join(args.out_dir, name)) if args.out_dir else (lambda name: None)
    check_fixed_and_start(sub("constraints"))
    check_max_latency(sub("max_latency"))
    print("All AUTO_PIPELINE latency constraint end-to-end tests passed.")


if __name__ == "__main__":
    main()
