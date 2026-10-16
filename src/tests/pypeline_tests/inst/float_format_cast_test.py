#!/usr/bin/env python3
# Known issue #376 (C front end): a conversion between two float formats is not an
# operator. C_TO_LOGIC leaves the connection as is and VHDL.py wraps it in the
# VHDL function resize_float_e_m_t, inline in the converting function's body.
# Two behaviors, one per --check:
#   values  out-of-range floats wrap instead of saturating when narrowed to
#           float_5_10_t (GHDL simulation of to_half's entity)
#   inline  the conversion logic (an exponent adder and a zero-detect mux) sits
#           in the user function's own body, where no delay measurement or
#           estimate sees it
# Both exit nonzero while the issue is present (registered expect_fail).
import argparse
import glob
import os
import shutil
import subprocess
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PYPELINEC = os.path.join(THIS_DIR, "../../../pypelinec")
DESIGN = os.path.join(THIS_DIR, "float_format_cast_design.c")

# float bits -> acceptable float_5_10_t bits from to_half
EXPECTED = [
    ("3F800000", ["3C00"], "1.0"),
    ("477FE000", ["7BFF"], "65504.0, the largest half value"),
    ("501502F9", ["7C00", "7BFF"], "1e10: infinity, or saturate to the max"),
    ("48127C00", ["7C00", "7BFF"], "1.5e5: infinity, or saturate to the max"),
    ("2EDBE6FF", ["0000"], "1e-10: below the smallest half value, so 0"),
]

TB_TEMPLATE = """library ieee;
use ieee.std_logic_1164.all;
entity tb is end tb;
architecture sim of tb is
  signal x : std_logic_vector(31 downto 0);
  signal y : std_logic_vector(15 downto 0);
  type vec_t is array (natural range <>) of std_logic_vector(31 downto 0);
  constant inputs : vec_t := ({inputs});
begin
  dut : entity work.{entity} port map (x => x, return_output => y);
  process begin
    for i in inputs'range loop
      x <= inputs(i);
      wait for 1 ns;
      report "in=" & to_hstring(inputs(i)) & " out=" & to_hstring(y);
    end loop;
    wait;
  end process;
end sim;
"""


def build(out_dir):
    cmd = [
        sys.executable,
        PYPELINEC,
        DESIGN,
        "--comb",
        "--no_synth",
        "--out_dir",
        out_dir,
    ]
    print("Running:", " ".join(cmd), flush=True)
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    print(result.stdout)
    if result.returncode != 0:
        print("SETUP FAILURE: pypelinec exited nonzero", result.returncode)
        sys.exit(2)


def func_vhd_files(out_dir, func_name):
    files = glob.glob(
        os.path.join(out_dir, "**", func_name, func_name + "_0CLK_*.vhd"),
        recursive=True,
    )
    if not files:
        print(f"SETUP FAILURE: no {func_name}_0CLK_*.vhd written")
        sys.exit(2)
    return files


def check_inline(out_dir):
    failed = False
    for func_name in ("to_half", "select_half"):
        for path in func_vhd_files(out_dir, func_name):
            with open(path) as f:
                for line in f:
                    if "resize_float_e_m_t(" in line:
                        print(
                            f"FAIL: {func_name} body converts inline: "
                            f"{line.strip()}"
                        )
                        failed = True
    if failed:
        sys.exit(1)
    print("Float-format conversions are submodules, not inline logic.")


def check_values(out_dir):
    entity = os.path.basename(func_vhd_files(out_dir, "to_half")[0])[:-4]
    sim_dir = os.path.join(out_dir, "ghdl_float_format_cast")
    os.makedirs(sim_dir, exist_ok=True)
    tb_path = os.path.join(sim_dir, "tb.vhd")
    inputs = ", ".join(f'x"{bits}"' for bits, _, _ in EXPECTED)
    with open(tb_path, "w") as f:
        f.write(TB_TEMPLATE.format(inputs=inputs, entity=entity))
    vhd_files = sorted(
        p
        for p in glob.glob(os.path.join(out_dir, "**", "*.vhd"), recursive=True)
        if not p.startswith(sim_dir)
    )
    workdir = ["--std=08", f"--workdir={sim_dir}"]
    for cmd in (
        ["ghdl", "-i"] + workdir + vhd_files + [tb_path],
        ["ghdl", "-m"] + workdir + ["tb"],
        ["ghdl", "-r"] + workdir + ["tb"],
    ):
        result = subprocess.run(
            cmd,
            cwd=sim_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if result.returncode != 0:
            print(result.stdout)
            print("SETUP FAILURE:", " ".join(cmd[:2]), "exited", result.returncode)
            sys.exit(2)
    outputs = {}
    for line in result.stdout.splitlines():
        if "in=" in line and " out=" in line:
            pair = line[line.index("in=") + 3 :].split(" out=")
            outputs[pair[0].strip()] = pair[1].strip()
    failed = False
    for bits, allowed, what in EXPECTED:
        got = outputs.get(bits)
        if got is None:
            print(f"SETUP FAILURE: no simulation output for {bits}")
            sys.exit(2)
        status = "ok" if got in allowed else "FAIL"
        print(f"{status}: {what}: {bits} -> {got} (expected {' or '.join(allowed)})")
        failed |= got not in allowed
    if failed:
        sys.exit(1)
    print("Float-format conversions saturate out-of-range values.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", choices=["values", "inline"], required=True)
    parser.add_argument("--out_dir", required=True)
    args = parser.parse_args()
    if args.check == "values" and shutil.which("ghdl") is None:
        print("SETUP FAILURE: ghdl not found")
        sys.exit(2)
    build(args.out_dir)
    if args.check == "inline":
        check_inline(args.out_dir)
    else:
        check_values(args.out_dir)


if __name__ == "__main__":
    main()
