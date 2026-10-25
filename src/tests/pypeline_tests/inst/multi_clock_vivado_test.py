"""Build multi_clock_synth_design.py with Vivado (the Arty's xc7a35ti) and
check the async FIFO hardware and the clock constraints.

- By default rx is Xilinx's xpm_fifo_async, at its minimum depth of 16.
- With FIFO_IMPL=builtin (rx: global_fifo(16, impl="builtin")) rx is the
  built-in async FIFO and no xpm_fifo_async is instantiated.
- Both builds: clocks.xdc creates every clock on its port and declares them
  asynchronous, and Vivado reports a PASS line for each clock.

The two --comb builds run at once, in their own out_dirs.

Run: python3 multi_clock_vivado_test.py --out_dir DIR
"""

import argparse
import json
import os
import re
import subprocess
import sys

INST_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(INST_DIR, "..", "..", "..", "pypelinec")
DESIGN = os.path.join(INST_DIR, "multi_clock_synth_design.py")
PART = "xc7a35ticsg324-1l"
CLOCKS = (("clk_125p0_eth_rx", "8.0"), ("clk_100p0", "10.0"), ("clk_50p0", "20.0"))


def check(name, build_dir, code, out, xpm):
    assert code == 0, f"{name}: build failed ({code})"
    xdc = open(os.path.join(build_dir, "clocks.xdc")).read()
    for clock, period in CLOCKS:
        assert f"create_clock -add -name {clock} -period {period} " in xdc, xdc
        assert f"[get_ports {{{clock}}}]" in xdc, xdc
        assert re.search(rf"^PASS Clock {clock} FMAX", out, re.M), f"{name}: no PASS for {clock}"
    assert "set_clock_groups -name async_clks_group -asynchronous" in xdc, xdc
    entities = open(os.path.join(build_dir, "clk_cross_entities.vhd")).read()
    records = json.load(open(os.path.join(build_dir, "clock_crossings.json")))
    rx = [r for r in records if r["crossing"] == "rx"]
    assert len(rx) == 1 and rx[0]["depth"] == 16, records
    if xpm:
        assert "xpm_fifo_async_inst : xpm_fifo_async" in entities
        assert "FIFO_WRITE_DEPTH => 16," in entities
        assert rx[0]["hardware"] == "xpm_fifo_async", rx
    else:
        assert "xpm_fifo_async" not in entities
        assert rx[0]["hardware"] == "built-in async", rx
    print(f"{name} PASS")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", required=True)
    args = parser.parse_args()
    builds = {"xpm": [], "builtin": ["-D", "FIFO_IMPL=builtin"]}
    procs = {}
    for name, extra in builds.items():
        build_dir = os.path.join(args.out_dir, name)
        procs[name] = (
            build_dir,
            subprocess.Popen(
                [sys.executable, PYPELINEC, DESIGN, "--comb", "--part", PART,
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
        check(name, build_dir, code, out, xpm=(name == "xpm"))
    print("multi_clock_vivado_test: all PASS")


if __name__ == "__main__":
    main()
