"""Build AUTO objects used at two clock goals with Vivado (the Arty's
xc7a35ti), all three builds at once, each timed on both clocks:

- auto_goal_vivado_design.py, two factory calls of one AUTO_PIPELINE factory
  (25 and 100 MHz), and the same built in a comprehension (LANES=list): the
  build succeeds, records one depth per goal (key@25p0mhz, key@100p0mhz), the
  100 MHz object's depth is deeper, and each object's factory-time .latency
  read matches what was built. Before goals were part of a key, both objects'
  products merged and the build stopped with an ambiguous .latency.
- auto_goal_shared_mcp_design.py, one AUTO_MULTI_CYCLE object under 50 and
  100 MHz MAINs: one count, which meets both clocks.

Run: python3 auto_goal_vivado_test.py --out_dir DIR
"""
import argparse
import json
import os
import re
import subprocess
import sys

INST_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(INST_DIR, "..", "..", "..", "pypelinec")
BUILDS = {
    "calls": ("auto_goal_vivado_design.py", []),
    "list": ("auto_goal_vivado_design.py", ["-D", "LANES=list"]),
    "mcp": ("auto_goal_shared_mcp_design.py", []),
}


def check(name, build_dir, code, out):
    assert code == 0, f"{name}: build failed ({code})"
    for main in ("slow", "fast"):
        assert re.search(rf"^PASS {main}: ", out, re.M), f"{name}: no PASS for {main}"
    record = json.load(open(os.path.join(build_dir, "built_hardware.json")))
    if name == "mcp":
        assert len(record["auto_multi_cycle_latencies"]) == 1, record
        return
    depths = record["auto_pipeline_latencies"]
    slow = [v for k, v in depths.items() if k.endswith("@25p0mhz")]
    fast = [v for k, v in depths.items() if k.endswith("@100p0mhz")]
    assert len(depths) == 2 and slow and fast, depths
    assert fast[0] > slow[0], depths
    assert "ambiguous .latency" not in out, out[-2000:]
    reads = re.findall(r"^  AUTO_PIPELINE (\S+): (\d+) -> (\S+)", out, re.M)
    assert reads and all(read == built for _key, read, built in reads[-2:]), reads


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", required=True)
    args = parser.parse_args()
    procs = {}
    for name, (design, extra) in BUILDS.items():
        build_dir = os.path.join(args.out_dir, name)
        procs[name] = (
            build_dir,
            subprocess.Popen(
                [sys.executable, PYPELINEC, os.path.join(INST_DIR, design),
                 "--out_dir", build_dir, *extra],
                cwd=args.out_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True,
            ),
        )
    results = {}
    for name, (build_dir, proc) in procs.items():
        out, _ = proc.communicate()
        # echoed so run_all's tool check sees the Vivado runs
        print(out)
        results[name] = (build_dir, proc.returncode, out)
    for name, (build_dir, code, out) in results.items():
        check(name, build_dir, code, out)
        print(f"{name} PASS")
    print("auto_goal_vivado_test: all PASS")


if __name__ == "__main__":
    main()
