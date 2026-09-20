#!/usr/bin/env python3
"""Reproducible ECP5 BRAM latency/frequency/resource frontier (no timeout)."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
DESIGN = ROOT / "src/tests/pypeline_tests/inst/auto_pipeline_ram_design.py"


def run_case(out, size, latency, seed):
    directory = out / f"size{size}_latency{latency}_seed{seed}"
    directory.mkdir(parents=True, exist_ok=True)
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith("AUTO_PIPELINE_RAM_")},
        "AUTO_PIPELINE_RAM_SIZE": str(size),
        "AUTO_PIPELINE_RAM_LATENCY": str(latency),
        "AUTO_PIPELINE_RAM_MHZ": "80",
        "PIPELINEC_OPEN_TOOLS_SEED": str(seed),
        "PIPELINEC_INTERNAL_SKIP_PIPELINE_MAP_PNG": "1",
    }
    cmd = [
        sys.executable,
        str(ROOT / "src/pypelinec"),
        str(DESIGN),
        "--comb",
        "--syn_tool",
        "open_tools",
        "--out_dir",
        str(directory),
    ]
    with (directory / "build.log").open("w") as log:
        rc = subprocess.run(
            cmd, env=env, stdout=log, stderr=subprocess.STDOUT
        ).returncode
    assert rc == 0, f"build failed: {directory / 'build.log'}"
    for line in (directory / "build.log").read_text().splitlines():
        if line.startswith("Running:"):
            print(line, flush=True)
    history = json.loads((directory / "top/sweep_history.json").read_text())
    plan = next(iter(history["auto_pipeline_rams"].values()))
    assert plan["latency"] == latency
    netlist_files = list((directory / "top").glob("top_*.json"))
    assert len(netlist_files) == 1, netlist_files
    netlist = json.loads(netlist_files[0].read_text())
    counts = {}
    for module in netlist["modules"].values():
        for cell in module.get("cells", {}).values():
            counts[cell["type"]] = counts.get(cell["type"], 0) + 1
    assert counts.get("DP16KD", 0) > 0, (directory, counts)
    log = next((directory / "top").glob("open_tools*.log")).read_text()
    frequencies = re.findall(r"Max frequency for clock .*?: ([0-9.]+) MHz", log)
    result = dict(
        size=size,
        latency=latency,
        seed=seed,
        mhz=float(frequencies[-1]),
        plan=plan,
        cells=counts,
        directory=str(directory),
    )
    print(
        f"RAM {size}x32 L={latency} seed={seed}: {result['mhz']} MHz, {counts['DP16KD']} BRAM",
        flush=True,
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out_dir", required=True)
    parser.add_argument("--sizes", nargs="+", type=int, default=[16384, 65536])
    parser.add_argument("--latencies", nargs="+", type=int, default=[1, 3, 5, 7, 9])
    parser.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3])
    parser.add_argument("-j", type=int, default=2)
    parser.add_argument("--require_improvement", action="store_true")
    args = parser.parse_args()
    out = Path(args.out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    cases = [
        (size, latency, seed)
        for size in args.sizes
        for latency in args.latencies
        for seed in args.seeds
    ]
    with ThreadPoolExecutor(max_workers=args.j) as pool:
        results = list(pool.map(lambda case: run_case(out, *case), cases))
    medians = {
        str(size): {
            str(latency): statistics.median(
                r["mhz"]
                for r in results
                if r["size"] == size and r["latency"] == latency
            )
            for latency in args.latencies
        }
        for size in args.sizes
    }
    with (out / "ram_qor.json").open("w") as f:
        json.dump(
            dict(part="LFE5U-85F-6BG381C", results=results, median_mhz=medians),
            f,
            indent=2,
        )
    if args.require_improvement:
        assert any(
            max(m[str(l)] for l in args.latencies if l > 3) > m["3"]
            for m in medians.values()
        ), medians
    print(json.dumps(medians, indent=2))


if __name__ == "__main__":
    main()
