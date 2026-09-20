#!/usr/bin/env python3
"""ECP5 inference, exact constraints, measured search, and failure diagnostics."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
DESIGN = Path(__file__).with_name("auto_pipeline_ram_design.py")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", required=True)
    parser.add_argument("--syn_tool", default="open_tools")
    args = parser.parse_args()
    assert args.syn_tool == "open_tools"
    out = Path(args.out_dir)

    def build(name, env, flags=(), success=True):
        directory = out / name
        directory.mkdir(parents=True, exist_ok=True)
        clean_env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("AUTO_PIPELINE_RAM_")
        }
        clean_env.update({k: str(v) for k, v in env.items()})
        cmd = [
            sys.executable,
            str(ROOT / "src/pypelinec"),
            str(DESIGN),
            "--syn_tool",
            args.syn_tool,
            "--pipeline_min_effort",
            "0",
            "--out_dir",
            str(directory),
            *flags,
        ]
        with (directory / "build.log").open("w") as log:
            rc = subprocess.run(
                cmd, env=clean_env, stdout=log, stderr=subprocess.STDOUT
            ).returncode
        text = (directory / "build.log").read_text()
        print(text, flush=True)
        assert (rc == 0) == success, (directory, rc)
        history = json.loads((directory / "top/sweep_history.json").read_text())
        plan = next(iter(history["auto_pipeline_rams"].values()))
        return directory, history, plan, text

    for latency, ports, bytes_ in (
        (1, "w,r", 0),
        (3, "rw,rw", 0),
        (5, "w,r", 1),
        (7, "w,r", 0),
        (5, "w,r,r,r", 0),
        (5, "rw,rw", 1),
    ):
        directory, history, plan, _ = build(
            f"fixed{latency}_{ports.replace(',', '_')}_bytes{bytes_}",
            dict(
                AUTO_PIPELINE_RAM_LATENCY=latency,
                AUTO_PIPELINE_RAM_PORTS=ports,
                AUTO_PIPELINE_RAM_BYTES=bytes_,
            ),
            ("--comb",),
        )
        assert plan["latency"] == latency
        counts = {}
        for path in (directory / "top").glob("top_*.json"):
            for module in json.loads(path.read_text())["modules"].values():
                for cell in module.get("cells", {}).values():
                    counts[cell["type"]] = counts.get(cell["type"], 0) + 1
        assert counts.get("DP16KD", 0) > 0, counts
        assert plan["banks"] > 1 if latency > 3 else plan["banks"] == 1
    _, history, plan, _ = build(
        "automatic", dict(AUTO_PIPELINE_RAM_MHZ=60, AUTO_PIPELINE_RAM_START=3)
    )
    assert plan["latency"] == 1  # a start guess can be trimmed
    assert history["auto_pipeline_ram_iterations"]
    _, history, plan, text = build(
        "capped",
        dict(AUTO_PIPELINE_RAM_MHZ=1000, AUTO_PIPELINE_RAM_MAX=1),
        success=False,
    )
    assert (
        plan["latency"] == 1
        and "auto-pipelined RAM latency limit" in text
        and "TIMING NOT MET" in text
    )
    print("All automatic pipeline RAM ECP5 build tests passed.")


if __name__ == "__main__":
    main()
