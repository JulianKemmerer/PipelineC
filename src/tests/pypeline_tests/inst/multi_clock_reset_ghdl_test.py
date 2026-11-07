"""Build multi_clock_reset_design.py (two clocks, each with its own reset)
with --comb --no_synth, then run the generated top in GHDL with a two-clock
testbench that resets each domain in turn: no synthesis tool runs.

- The top maps each MAIN's RESET port to its domain's reset: the cpu
  domain's MAINs, its global instance and its FIFO to cpu_rst, eth_main to
  eth_rst; the reset generators get none.
- The testbench pulses BTN (the cpu reset) and later ETH_RST_REQ (the eth
  IP block's reset request), each through its domain's synchronizer: the
  domain reset restarts (its count drops, the cpu FIFO's sum starts over)
  while the other domain keeps counting.

Run: python3 multi_clock_reset_ghdl_test.py --out_dir DIR   (needs ghdl)
"""

import argparse
import os
import re
import shutil
import subprocess
import sys

INST_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(INST_DIR, "..", "..", "..", "pypelinec")
DESIGN = os.path.join(INST_DIR, "multi_clock_reset_design.py")

TB = """
library ieee; use ieee.std_logic_1164.all; use ieee.numeric_std.all;
entity tb is end tb;
architecture sim of tb is
  signal clk_100p0_cpu : std_logic := '0';
  signal ETH_RX_CLK : unsigned(0 downto 0) := "0";
  signal BTN, ETH_RST_REQ : unsigned(0 downto 0) := "0";
  signal CPU_COUNT, ETH_COUNT, ETH_SEEN, FIFO_SUM : unsigned(15 downto 0);
  procedure show(tag : string; c, e, f : unsigned) is
  begin
    report "SAMPLE " & tag & " cpu=" & integer'image(to_integer(c))
      & " eth=" & integer'image(to_integer(e))
      & " sum=" & integer'image(to_integer(f));
  end procedure;
begin
  clk_100p0_cpu <= not clk_100p0_cpu after 5 ns;  -- 100 MHz
  ETH_RX_CLK <= not ETH_RX_CLK after 4 ns;        -- 125 MHz
  dut: entity work.top port map (
    clk_100p0_cpu => clk_100p0_cpu, ETH_RX_CLK => ETH_RX_CLK,
    BTN => BTN, ETH_RST_REQ => ETH_RST_REQ,
    CPU_COUNT => CPU_COUNT, ETH_COUNT => ETH_COUNT, ETH_SEEN => ETH_SEEN,
    FIFO_SUM => FIFO_SUM);
  process begin
    BTN <= "1"; wait for 50 ns; BTN <= "0";   -- power-on reset of the cpu domain
    wait for 950 ns;
    show("a", CPU_COUNT, ETH_COUNT, FIFO_SUM);
    BTN <= "1"; wait for 50 ns; BTN <= "0";   -- reset the cpu domain
    wait for 250 ns;
    show("b", CPU_COUNT, ETH_COUNT, FIFO_SUM);
    ETH_RST_REQ <= "1"; wait for 50 ns; ETH_RST_REQ <= "0";  -- reset the eth domain
    wait for 250 ns;
    show("c", CPU_COUNT, ETH_COUNT, FIFO_SUM);
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


def check_top(build_dir):
    top = open(os.path.join(build_dir, "top", "top.vhd")).read()
    maps = {}
    for inst, body in re.findall(r"^(\w+) : entity work\.\w+ port map \((.*?)\);", top, re.M | re.S):
        maps[re.sub(r"_0CLK_\w+$", "", inst)] = body
    for main in ("cpu_main", "summer_INST", "words_FIFO"):
        assert "module_to_global.btn_sync.cpu_rst(0)" in maps[main], (main, maps[main])
    assert "module_to_global.eth_rst_gen.eth_rst(0)" in maps["eth_main"], maps["eth_main"]
    for main in ("btn_sync", "eth_rst_gen"):
        assert "_rst(0)" not in maps[main], (main, maps[main])
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
    samples = {
        tag: (int(c), int(e), int(s))
        for tag, c, e, s in re.findall(r"SAMPLE (\w) cpu=(\d+) eth=(\d+) sum=(\d+)", out)
    }
    print(f"GHDL samples: {samples}")
    (ca, ea, sa), (cb, eb, sb), (cc, ec, sc) = samples["a"], samples["b"], samples["c"]
    # The cpu reset restarts the cpu domain and its FIFO; eth keeps counting
    assert cb < ca and cb < 40 and sb < sa, samples
    assert eb > ea, samples
    # The eth reset restarts the eth domain; cpu keeps counting
    assert ec < eb and ec < 40, samples
    assert cc > cb, samples
    print("check_ghdl PASS")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", required=True)
    args = parser.parse_args()
    if shutil.which("ghdl") is None:
        print("SETUP FAILURE: ghdl not found")
        sys.exit(2)
    build_dir = build(args.out_dir)
    check_top(build_dir)
    check_ghdl(build_dir, args.out_dir)
    print("multi_clock_reset_ghdl_test: all PASS")


if __name__ == "__main__":
    main()
