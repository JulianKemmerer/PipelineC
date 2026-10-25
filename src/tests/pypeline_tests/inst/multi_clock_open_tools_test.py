"""Build multi-clock designs with open_tools (ECP5 nextpnr) and check what
the timing reports and the sweep do with more than one clock.

- --comb of multi_clock_synth_design.py: clocks.py declares all three
  clocks, nextpnr reports a PASS line for each, and the async FIFO rx is the
  built-in async FIFO (the crossing report says so).
- --comb of multi_clock_design.py, whose eth_clk arrives on the pin
  ETH_RX_CLK: nextpnr reports that clock by the pin's name, and the build
  still gives it its PASS line under clk_125p0_eth_rx.
- A sweep of the same design at CRUNCH_MHZ=80: the 32-bit multiply in crunch
  (about 77 MHz as written) gets a pipeline cut and meets 80 MHz; the async
  FIFO's side MAINs rx_FIFO_wr / rx_FIFO_rd get no stages.
- A sweep of multi_clock_fifo_timing_design.py at its 900 MHz read clock: the
  worst path of mon_clk is inside the async FIFO mon, so the build fails with
  TIMING NOT MET naming "global FIFO mon" and its source line, and does not
  dismiss the path as "likely only limited by built in FIFO implementations".

Run: python3 multi_clock_open_tools_test.py --out_dir DIR
"""

import argparse
import json
import os
import re
import subprocess
import sys

INST_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(INST_DIR, "..", "..", "..", "pypelinec")
SYNTH_DESIGN = os.path.join(INST_DIR, "multi_clock_synth_design.py")
PIN_CLOCK_DESIGN = os.path.join(INST_DIR, "multi_clock_design.py")
FIFO_TIMING_DESIGN = os.path.join(INST_DIR, "multi_clock_fifo_timing_design.py")


def _build(out_dir, name, design, *args):
    build_dir = os.path.join(out_dir, name)
    proc = subprocess.run(
        [sys.executable, PYPELINEC, design, "--syn_tool", "open_tools",
         "--out_dir", build_dir, *args],
        cwd=out_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    # echoed so run_all's tool check sees the open_tools runs
    print(proc.stdout)
    return proc.returncode, proc.stdout, build_dir


def check_comb(out_dir):
    code, out, build_dir = _build(out_dir, "comb", SYNTH_DESIGN, "--comb")
    assert code == 0, f"--comb build failed ({code})"
    clocks = open(os.path.join(build_dir, "clocks.py")).read()
    for clock, mhz in (("clk_125p0_eth_rx", 125.0), ("clk_100p0", 100.0), ("clk_50p0", 50.0)):
        assert f'ctx.addClock("{clock}", {mhz})' in clocks, clocks
        assert re.search(rf"^PASS Clock {clock} FMAX", out, re.M), f"no PASS line for {clock}"
    records = json.load(open(os.path.join(build_dir, "clock_crossings.json")))
    rx = [r for r in records if r["crossing"] == "rx"]
    assert len(rx) == 1 and rx[0]["hardware"] == "built-in async", records
    print("check_comb PASS")


def check_pin_clock(out_dir):
    code, out, _ = _build(out_dir, "pin_clock", PIN_CLOCK_DESIGN, "--comb")
    assert code == 0, f"--comb build of the pin-clocked design failed ({code})"
    for clock in ("clk_125p0_eth_rx", "clk_100p0"):
        assert re.search(rf"^PASS Clock {clock} FMAX", out, re.M), f"no PASS line for {clock}"
    print("check_pin_clock PASS")


def check_sweep(out_dir):
    code, out, _ = _build(out_dir, "sweep", SYNTH_DESIGN, "-D", "CRUNCH_MHZ=80")
    assert code == 0, f"sweep at CRUNCH_MHZ=80 failed ({code})"
    assert "TIMING NOT MET" not in out
    match = re.search(r"^\[sweep\]   crunch: (\d+) slice\(s\) total", out, re.M)
    assert match and int(match.group(1)) >= 1, "crunch got no pipeline cut"
    for side in ("rx_FIFO_wr", "rx_FIFO_rd"):
        assert not re.search(rf"^\[sweep\]   {side}: [1-9]\d* slice", out, re.M), (
            f"{side} was pipelined"
        )
    print(f"check_sweep PASS (crunch: {match.group(1)} slice(s))")


def check_fifo_timing(out_dir):
    code, out, _ = _build(out_dir, "fifo_timing", FIFO_TIMING_DESIGN)
    assert code != 0, "a FIFO path missing 900 MHz did not fail the build"
    expected = (
        "ERROR: TIMING NOT MET: global FIFO mon [multi_clock_fifo_timing_design.py:15]"
    )
    assert expected in out, f"expected {expected!r}"
    assert "likely only limited" not in out
    for main in ("mon_source", "mon_sink"):
        assert not re.search(rf"TIMING NOT MET: {main}\b", out), f"{main} was blamed"
    print("check_fifo_timing PASS")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", required=True)
    args = parser.parse_args()
    check_comb(args.out_dir)
    check_pin_clock(args.out_dir)
    check_sweep(args.out_dir)
    check_fifo_timing(args.out_dir)
    print("multi_clock_open_tools_test: all PASS")


if __name__ == "__main__":
    main()
