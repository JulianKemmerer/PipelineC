"""Build multi_clock_design.py (two clocks, an async global FIFO, a sync
global FIFO and an async wire) with --comb --no_synth, then check the
generated design in GHDL: no synthesis tool runs.

- The crossing report lists the three crossings with their clocks, kinds,
  hardware and depths.
- The top level has the clock port clk_100p0, the pin ETH_RX_CLK carrying
  eth_clk, and the async FIFO's clk_cross_rx_FIFO instance.
- A two-clock VHDL testbench (eth_clk at 125 MHz, clk_100p0 at 100 MHz) runs
  the top for 2 us: bytes cross the built-in async FIFO in order
  (RX_ERRORS = 0, RX_COUNT counting), and the synchronized link flag rises.

Run: python3 multi_clock_ghdl_test.py --out_dir DIR   (needs ghdl)
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

INST_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(INST_DIR, "..", "..", "..", "pypelinec")
DESIGN = os.path.join(INST_DIR, "multi_clock_design.py")

TB = """
library ieee; use ieee.std_logic_1164.all; use ieee.numeric_std.all;
entity tb is end tb;
architecture sim of tb is
  signal clk_100p0 : std_logic := '0';
  signal ETH_RX_CLK : unsigned(0 downto 0) := "0";
  signal RX_COUNT, RX_ERRORS : unsigned(7 downto 0);
  signal LINK : unsigned(0 downto 0);
begin
  clk_100p0 <= not clk_100p0 after 5 ns;   -- 100 MHz
  ETH_RX_CLK <= not ETH_RX_CLK after 4 ns; -- 125 MHz
  dut: entity work.top port map (
    clk_100p0 => clk_100p0, ETH_RX_CLK => ETH_RX_CLK,
    RX_COUNT => RX_COUNT, RX_ERRORS => RX_ERRORS, LINK => LINK);
  process begin
    wait for 2 us;
    report "RESULT count=" & integer'image(to_integer(RX_COUNT))
      & " errors=" & integer'image(to_integer(RX_ERRORS))
      & " link=" & integer'image(to_integer(LINK));
    std.env.finish;
  end process;
end;
"""


def _run(cmd, cwd):
    proc = subprocess.run(
        cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    return proc.returncode, proc.stdout


def build(out_dir):
    build_dir = os.path.join(out_dir, "build")
    code, out = _run(
        [sys.executable, PYPELINEC, DESIGN, "--comb", "--no_synth", "--out_dir", build_dir],
        out_dir,
    )
    print(out)
    assert code == 0, f"build failed ({code})"
    return build_dir


def check_report(build_dir):
    records = json.load(open(os.path.join(build_dir, "clock_crossings.json")))
    got = [
        (r["crossing"], r["write_clock"], r["read_clock"], r["kind"], r["hardware"], r["depth"])
        for r in records
    ]
    expected = [
        ("rx", "clk_125p0_eth_rx", "clk_100p0", "global_fifo", "built-in async", 16),
        ("cmds", "clk_100p0", "clk_100p0", "global_sync_fifo", "make_stream_fifo", 4),
        ("link_up", "clk_125p0_eth_rx", "clk_100p0", "ASYNC wire", "none", None),
    ]
    assert got == expected, got
    text = open(os.path.join(build_dir, "clock_crossings.log")).read()
    assert re.search(r"^rx\s+eth_clk -> clk_100p0\s+global_fifo\s+built-in async", text, re.M), text
    print("check_report PASS")


def check_top(build_dir):
    top = open(os.path.join(build_dir, "top", "top.vhd")).read()
    for token in (
        "clk_100p0 : in std_logic",
        "ETH_RX_CLK : in unsigned(0 downto 0)",
        "clk_125p0_eth_rx <= ETH_RX_CLK(0);",
        "rx_FIFO : entity work.clk_cross_rx_FIFO",
        "in_clk => clk_125p0_eth_rx",
        "out_clk => clk_100p0",
    ):
        assert token in top, f"expected {token!r} in top.vhd"
    print("check_top PASS")


def check_ghdl(build_dir, out_dir):
    sim_dir = os.path.join(out_dir, "ghdl")
    os.makedirs(sim_dir, exist_ok=True)
    tb_path = os.path.join(sim_dir, "tb.vhd")
    with open(tb_path, "w") as f:
        f.write(TB)
    vhd_files = open(os.path.join(build_dir, "vhdl_files.txt")).read().split()
    workdir = ["--std=08", "-frelaxed", f"--workdir={sim_dir}"]
    for cmd in (
        ["ghdl", "-i"] + workdir + vhd_files + [tb_path],
        ["ghdl", "-m"] + workdir + ["tb"],
        ["ghdl", "-r"] + workdir + ["tb"],
    ):
        code, out = _run(cmd, sim_dir)
        assert code == 0, f"{' '.join(cmd[:2])} failed:\n{out[-4000:]}"
    match = re.search(r"RESULT count=(\d+) errors=(\d+) link=(\d+)", out)
    assert match, out[-2000:]
    count, errors, link = (int(g) for g in match.groups())
    print(f"GHDL: count={count} errors={errors} link={link}")
    # 200 read-clock cycles (RX_COUNT is 8 bits); a word crosses about every
    # cycle once filled
    assert errors == 0 and link == 1 and count >= 150, (count, errors, link)
    print("check_ghdl PASS")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", required=True)
    args = parser.parse_args()
    if shutil.which("ghdl") is None:
        print("SETUP FAILURE: ghdl not found")
        sys.exit(2)
    build_dir = build(args.out_dir)
    check_report(build_dir)
    check_top(build_dir)
    check_ghdl(build_dir, args.out_dir)
    print("multi_clock_ghdl_test: all PASS")


if __name__ == "__main__":
    main()
