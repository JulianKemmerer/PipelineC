#!/usr/bin/env python3
"""A RAM under an active reset still maps to block RAM: builds
ram_reset_inference_design.py (a 4096 x 32 RAM under reset_registers="all")
as make_ram and as make_auto_pipeline_ram with --comb on one tool, checks that
the RAM's entity has the reset, and that synthesis used block RAM, not
flip-flops (a reset on the memory or its read registers stops block RAM
inference).

Run: python3 ram_reset_inference_test.py --syn_tool open_tools|vivado --out_dir DIR
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
DESIGN = Path(__file__).with_name("ram_reset_inference_design.py")


def build(out, syn_tool, kind):
    directory = out / kind
    directory.mkdir(parents=True, exist_ok=True)
    target = ["--part", "xc7a200tffg1156-2"] if syn_tool == "vivado" else []
    cmd = [sys.executable, str(ROOT / "src/pypelinec"), str(DESIGN), "--comb",
           "--syn_tool", syn_tool, *target, "-D", f"RAM_RESET_KIND={kind}",
           "--out_dir", str(directory)]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    print(proc.stdout, flush=True)
    assert proc.returncode == 0, (kind, proc.returncode)
    return directory


def ram_entity_has_reset(directory):
    # The RAM's raw-VHDL entity holds the reset block (ram.py's "cleared" list)
    for path in directory.rglob("*.vhd"):
        text = path.read_text()
        if "ram_mem" in text and "if RESET = '1' then" in text:
            return True
    return False


def resources(directory, syn_tool):
    if syn_tool == "vivado":
        sys.path.insert(0, str(ROOT / "src"))
        from VIVADO import PARSE_RAM_RESOURCES

        history = json.loads((directory / "top/sweep_history.json").read_text())
        log = Path(history["retained_observation"]["log_path"]).read_text()
        counts = PARSE_RAM_RESOURCES(log)
        return counts["RAMB18"] + 2 * counts["RAMB36"], counts["FF"], counts
    counts = {}
    for path in (directory / "top").glob("top_*.json"):
        for module in json.loads(path.read_text())["modules"].values():
            for cell in module.get("cells", {}).values():
                counts[cell["type"]] = counts.get(cell["type"], 0) + 1
    return counts.get("DP16KD", 0), counts.get("TRELLIS_FF", 0), counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", required=True)
    parser.add_argument("--syn_tool", required=True, choices=("open_tools", "vivado"))
    args = parser.parse_args()
    for kind in ("plain", "auto"):
        directory = build(Path(args.out_dir), args.syn_tool, kind)
        assert ram_entity_has_reset(directory), f"{kind}: the RAM entity has no reset"
        brams, ffs, counts = resources(directory, args.syn_tool)
        # 128 Kibit: at least four 36 Kibit block RAMs (eight 18 Kibit ones)
        assert brams >= 4, (kind, counts)
        assert ffs < 4096, (kind, counts)  # the memory did not become registers
        print(f"{kind}: block RAM units {brams}, flip-flops {ffs}")
    print(f"ram_reset_inference_test ({args.syn_tool}): all PASS")


if __name__ == "__main__":
    main()
