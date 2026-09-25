#!/usr/bin/env python3
"""OpenXC7 --pins builds end to end: board-facing implementation, Project X-Ray
conversion, and a bitstream that honors the pin constraints.

Builds examples/pypeline/blink.py for a Basys 3 (xc7a35tcpg236-1) with
constraints/openxc7_basys3_blink.xdc:

- "full": the sweep times -noiopad characterization tops, then
  GENERATE_BITSTREAM implements the board-facing top;
- "comb": --comb times a characterization top the same way;
- "full rerun": "full" again, into the same out_dir (after it finished).

Each build must implement the board-facing top exactly once, into an
open_tools_final.log holding that one nextpnr run (no earlier run appended),
and leave top/top.bit for the right device (its IDCODE write matches Project
X-Ray's part.yaml), with every XDC PACKAGE_PIN's IOB tile configured in
top/top.fasm.
"""

import argparse
import csv
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
DESIGN = ROOT / "examples/pypeline/blink.py"
XDC = Path(__file__).resolve().parents[1] / "constraints/openxc7_basys3_blink.xdc"
PART = "xc7a35tcpg236-1"

sys.path.insert(0, str(ROOT / "src"))
import C_TO_LOGIC  # Establish PipelineC's normal module-import order.
import OPEN_TOOLS

SYNC_WORD = bytes.fromhex("aa995566")
IDCODE_WRITE = bytes.fromhex("30018001")  # type 1 packet: write 1 word to IDCODE
# The board-facing implementation's log, as SYN_AND_REPORT_TIMING_NEW announces it
FINAL_RUN_RE = re.compile(r"^Running: (\S*/top/open_tools_final\S*\.log)$", re.M)


def xdc_package_pins(xdc_text):
    """{port: package pin} from the XDC's PACKAGE_PIN ... [get_ports ...] lines."""
    pins = {}
    for line in xdc_text.splitlines():
        m = re.search(r"PACKAGE_PIN\s+(\w+).*\[get_ports\s+\{?(.+?)\}?\]\s*$", line)
        if m:
            pins[m.group(2)] = m.group(1)
    assert pins, f"no PACKAGE_PIN constraints in {XDC}"
    return pins


def check_bitstream(top_dir, part_yaml):
    for name in ("top.fasm", "top.frames", "top.bit"):
        assert (top_dir / name).is_file(), f"missing {top_dir / name}"

    bit = (top_dir / "top.bit").read_bytes()
    sync = bit.find(SYNC_WORD)
    assert sync >= 0, "top.bit has no configuration sync word"
    idcode_at = bit.find(IDCODE_WRITE, sync)
    assert idcode_at >= 0, "top.bit never writes the IDCODE register"
    got = int.from_bytes(bit[idcode_at + 4 : idcode_at + 8], "big")
    want = int(
        re.search(r"^idcode:\s*(0x[0-9a-fA-F]+)", part_yaml.read_text(), re.M)[1], 16
    )
    assert got == want, f"top.bit IDCODE {got:#010x}, {PART} is {want:#010x}"

    # The XDC reached the implementation, not just the command line: each
    # constrained pin's IOB tile is configured in the FASM the .bit came from.
    with (part_yaml.parent / "package_pins.csv").open() as f:
        pin_to_tile = {row["pin"]: row["tile"] for row in csv.DictReader(f)}
    fasm_tiles = {
        line.split(".", 1)[0]
        for line in (top_dir / "top.fasm").read_text().splitlines()
        if line and not line.startswith("#")
    }
    for port, pin in xdc_package_pins(XDC.read_text()).items():
        tile = pin_to_tile[pin]
        assert tile in fasm_tiles, f"{port} -> {pin}: IOB tile {tile} not in top.fasm"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", required=True)
    parser.add_argument("--syn_tool", default="open_tools")
    args = parser.parse_args()
    assert args.syn_tool == "open_tools"
    out = Path(args.out_dir)

    # The backend's own preflight: fails naming whatever part of the OpenXC7
    # install is missing, and locates the part's Project X-Ray files.
    _, _, _, part_yaml = OPEN_TOOLS.GET_XC7_BITSTREAM_TOOLS_AND_DB(PART)
    part_yaml = Path(part_yaml)

    for label, name, flags in (
        ("full", "full", ()),
        ("comb", "comb", ("--comb",)),
        ("full rerun", "full", ()),
    ):
        directory = out / name  # one pypelinec process per out_dir at a time
        directory.mkdir(parents=True, exist_ok=True)
        cmd = [
            sys.executable,
            str(ROOT / "src/pypelinec"),
            str(DESIGN),
            "--part",
            PART,
            "--syn_tool",
            args.syn_tool,
            "--pins",
            str(XDC),
            "--out_dir",
            str(directory),
            *flags,
        ]
        log_path = directory / f"build_{label.replace(' ', '_')}.log"
        with log_path.open("w") as log:
            rc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT).returncode
        text = log_path.read_text()
        print(text, flush=True)
        assert rc == 0, (label, rc)

        final_runs = FINAL_RUN_RE.findall(text)
        assert (
            len(final_runs) == 1
        ), f"{label}: {len(final_runs)} board-facing implementations, expected 1"
        # blink has one clock, so one nextpnr run constrains exactly one
        nextpnr_runs = (
            Path(final_runs[0]).read_text().count("Info: constraining clock net")
        )
        assert (
            nextpnr_runs == 1
        ), f"{label}: {final_runs[0]} holds {nextpnr_runs} nextpnr runs, expected 1"

        check_bitstream(directory / "top", part_yaml)
        print(f"[PASS] {label}: top.bit for {PART}, XDC pins placed", flush=True)


if __name__ == "__main__":
    main()
