#!/usr/bin/env python3
"""--module_prefix: builds that declare the same unit names with different
text can share one project (PipelineC#400, wireguard-fpga#59).

module_prefix_design.py built with -D VARIANT=2 and -D VARIANT=3 gives the same
entity name (scale_...), c_structs_pkg and global_wires_pkg with different
text. Seven elaboration-only builds (--comb --no_synth, no synthesis tool),
the first six side by side:

  a, b            --module_prefix a_ / b_ and --verilog, VARIANT 2 and 3
  plain_a/_b      the same two designs without a prefix
  vivado, quartus the design with a part of each tool, which write the tool's file list
  a_rebuilt       a copy of a's output, rebuilt without the flag

and these checks:

- test_fixture_clashes_without_prefix: the unprefixed pair shares file names
  whose text differs, so the checks below are not vacuous.
- test_only_top_unprefixed: every unit, file name and reference of the final
  files starts with the prefix, except the --top entity.
- test_prefixed_vhdl_links_in_one_library: GHDL analyzes both file lists into
  one library and a testbench instantiates both cores; each one computes its
  own variant (x + 2 and x + 3), not the other build's scale.
- test_prefixed_verilog_links_in_one_design: Yosys reads both Verilog exports
  with no -overwrite, which refuses a repeated module name.
- test_vivado_and_quartus_lists_name_the_copy: read_vhdl.tcl and pipelinec_top.qip
  (builds with a Vivado and a Quartus part; neither tool runs) list the copy.
- test_default_build_has_no_namespaced_copy / _unprefixed_rebuild_removes_stale_copy:
  a build without the flag lists the unrenamed files and leaves no copy.
- test_bad_prefix_is_refused_before_building.
"""

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMPILER = HERE.parents[2] / "pypelinec"
DESIGN = HERE / "module_prefix_design.py"

# build name -> (top, VARIANT, prefix, other pypelinec options)
BUILDS = {
    "a": ("core_a", "2", "a_", ["--verilog"]),
    "b": ("core_b", "3", "b_", ["--verilog"]),
    "plain_a": ("core_a", "2", None, []),
    "plain_b": ("core_b", "3", None, []),
    # Parts that write read_vhdl.tcl and pipelinec_top.qip (neither tool runs)
    "vivado": ("core_v", "2", "v_", ["--part", "xc7a35tcpg236-1"]),
    "quartus": ("core_q", "2", "q_", ["--part", "5CSEBA6U23I7"]),
}

OUT = None  # Output root of this run (set by main)
BUILT = {}  # Build name -> its output directory, once built


def run_build(out, top, variant, prefix, options, log_name):
    cmd = [sys.executable, str(COMPILER), str(DESIGN), "--comb", "--no_synth"]
    cmd += ["--top", top, "-D", f"VARIANT={variant}", "--out_dir", str(out)]
    cmd += options
    if prefix:
        cmd += ["--module_prefix", prefix]
    log = OUT / log_name
    with open(log, "w") as f:
        result = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, text=True)
    text = log.read_text()
    assert result.returncode == 0, f"{' '.join(cmd)} failed:\n{text[-2000:]}"
    # A local named like a VHDL reserved word is renamed with only a warning
    assert "not a legal VHDL identifier" not in text, text
    return out


def build_all():
    if BUILT:
        return
    # Independent output directories, so the builds can run side by side
    with ThreadPoolExecutor(max_workers=len(BUILDS)) as pool:
        futures = {
            name: pool.submit(
                run_build, OUT / name, top, variant, prefix, options, name + ".log"
            )
            for name, (top, variant, prefix, options) in BUILDS.items()
        }
        for name, future in futures.items():
            BUILT[name] = future.result()


def listed_files(name):
    """The paths of a build's vhdl_files.txt."""
    build_all()
    return [Path(p) for p in (BUILT[name] / "vhdl_files.txt").read_text().split()]


def declared_units(text):
    return re.findall(r"(?im)^\s*(?:entity|package)\s+(\w+)\s+is\b", text)


def references(text):
    """Unit names a file's code refers to through the work library."""
    code = re.sub(r"--[^\n]*", "", text)
    return re.findall(r"(?i)\bwork\.(\w+)", code)


def tool(name):
    path = shutil.which(name)
    assert path, f"{name} is required"
    return path


def test_fixture_clashes_without_prefix():
    a = {p.name: p for p in listed_files("plain_a")}
    b = {p.name: p for p in listed_files("plain_b")}
    differing = sorted(
        n for n in set(a) & set(b) if a[n].read_text() != b[n].read_text()
    )
    assert "c_structs_pkg.pkg.vhd" in differing, differing
    assert "global_wires_pkg.pkg.vhd" in differing, differing
    assert any(n.startswith("scale_") for n in differing), differing


def test_only_top_unprefixed():
    for name in ("a", "b"):
        top, _, prefix, _ = BUILDS[name]
        files = listed_files(name)
        namespaced = BUILT[name] / top / "vhdl"
        plain = listed_files("plain_" + name)
        assert len(files) == len(plain), (len(files), len(plain))
        assert sorted(p.name for p in namespaced.iterdir()) == sorted(
            p.name for p in files
        ), "the directory holds exactly the listed files"
        for path in files:
            assert path.parent == namespaced, path
            assert path.name == f"{top}.vhd" or path.name.startswith(prefix), path
            text = path.read_text()
            for unit in declared_units(text):
                assert unit == top or unit.startswith(prefix), (path.name, unit)
            for unit in references(text):
                assert unit.startswith(prefix), (path.name, unit)
        top_text = (namespaced / f"{top}.vhd").read_text()
        assert re.search(rf"(?im)^\s*entity\s+{top}\s+is\b", top_text)
        assert f"use work.{prefix}c_structs_pkg.all;" in top_text


def port_type(top_vhd, port):
    match = re.search(rf"(?m)^{port}\s*:\s*(?:in|out)\s+([^;\n]+?)\s*;?\s*$", top_vhd)
    assert match, port
    return match.group(1)


def test_prefixed_vhdl_links_in_one_library():
    ghdl = tool("ghdl")
    build_all()
    signals = ""
    maps = ""
    for name, short in (("a", "a"), ("b", "b")):
        top = BUILDS[name][0]
        text = (BUILT[name] / top / "vhdl" / f"{top}.vhd").read_text()
        signals += (
            f"  signal {short}_dbg : {port_type(text, 'prefix_debug')};\n"
            f"  signal {short}_ret : "
            f"{port_type(text, 'module_prefix_core_return_output')};\n"
        )
        maps += (
            f"  {short}_core : entity work.{top} port map (\n"
            f"    clk_100p0 => clk, prefix_debug => {short}_dbg,\n"
            f"    module_prefix_core_x => x, module_prefix_core_valid => valid,\n"
            f"    module_prefix_core_return_output => {short}_ret);\n"
        )
    testbench = f"""library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.a_c_structs_pkg.all;
use work.b_c_structs_pkg.all;

entity link_tb is
end link_tb;

architecture sim of link_tb is
  signal clk : std_logic := '0';
  signal x : unsigned(7 downto 0) := to_unsigned(10, 8);
  signal valid : unsigned(0 downto 0) := to_unsigned(1, 1);
{signals}begin
  clk <= not clk after 5 ns;
{maps}  check : process
  begin
    wait for 500 ns;
    -- The FIFO has passed scale(x) through: x + 2 and x + 3
    assert to_integer(a_dbg) = 12
      report "core_a output " & integer'image(to_integer(a_dbg)) & ", want 12"
      severity failure;
    assert to_integer(b_dbg) = 13
      report "core_b output " & integer'image(to_integer(b_dbg)) & ", want 13"
      severity failure;
    report "LINK PASS";
    wait;
  end process;
end sim;
"""
    work = OUT / "ghdl_work"
    work.mkdir(exist_ok=True)
    tb_path = OUT / "link_tb.vhd"
    tb_path.write_text(testbench)
    options = ["--std=08", "-frelaxed", "--workdir=" + str(work)]
    files = [str(p) for p in listed_files("a") + listed_files("b")] + [str(tb_path)]
    for step in (
        ["-i"] + options + files,
        ["-m"] + options + ["link_tb"],
        ["-r"] + options + ["link_tb", "--stop-time=1us"],
    ):
        result = subprocess.run(
            [ghdl] + step,
            cwd=str(work),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        assert (
            result.returncode == 0
        ), f"ghdl {step[0]} failed:\n{result.stdout[-3000:]}"
    assert "LINK PASS" in result.stdout, result.stdout


def verilog_modules(path):
    return re.findall(r"(?m)^module\s+(\S+?)\s*\(", path.read_text())


def test_prefixed_verilog_links_in_one_design():
    yosys = tool("yosys")
    build_all()
    modules = {}
    for name in ("a", "b"):
        top, _, prefix, _ = BUILDS[name]
        path = BUILT[name] / top / f"{top}.v"
        modules[name] = verilog_modules(path)
        assert top in modules[name], modules[name][:5]
        assert all(m == top or m.startswith(prefix) for m in modules[name]), [
            m for m in modules[name] if m != top and not m.startswith(prefix)
        ]
    assert not set(modules["a"]) & set(modules["b"])
    for top in ("core_a", "core_b"):
        script = (
            f"read_verilog {BUILT['a'] / 'core_a' / 'core_a.v'}; "
            f"read_verilog {BUILT['b'] / 'core_b' / 'core_b.v'}; "
            f"hierarchy -check -top {top}"
        )
        result = subprocess.run(
            [yosys, "-q", "-p", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        assert result.returncode == 0, result.stdout[-3000:]


def test_vivado_and_quartus_lists_name_the_copy():
    for name in ("vivado", "quartus"):
        listed = listed_files(name)
        top = BUILDS[name][0]
        assert all(p.parent == BUILT[name] / top / "vhdl" for p in listed), listed
    # read_vhdl.tcl: one read_vhdl of the listed files, relative to its directory
    tcl = (BUILT["vivado"] / "read_vhdl.tcl").read_text()
    (group,) = re.findall(r"(?m)^read_vhdl[^\n]*?\{([^}]+)\}", tcl)
    root = str(BUILT["vivado"])
    assert [Path(p.replace("$thisDir", root)) for p in group.split()] == listed_files(
        "vivado"
    )
    # pipelinec_top.qip: the listed files, then the ieee_proposed library files
    qip = (BUILT["quartus"] / "pipelinec_top.qip").read_text()
    quoted = re.findall(
        r'VHDL_FILE \[file join \$::quartus\(qip_path\) "([^"]+)"\]', qip
    )
    own = [BUILT["quartus"] / p for p in quoted if not p.startswith("ieee_proposed/")]
    assert own == listed_files("quartus")


def test_default_build_has_no_namespaced_copy():
    for name in ("plain_a", "plain_b"):
        top = BUILDS[name][0]
        assert not (BUILT[name] / top / "vhdl").exists()
        assert all("/vhdl/" not in str(p) for p in listed_files(name))


def test_unprefixed_rebuild_removes_stale_copy():
    top, variant, _, options = BUILDS["a"]
    copy = OUT / "a_rebuilt"
    shutil.copytree(BUILT["a"], copy)
    assert (copy / top / "vhdl").is_dir()
    run_build(copy, top, variant, None, [], "a_rebuilt.log")
    assert not (copy / top / "vhdl").exists()
    listed = (copy / "vhdl_files.txt").read_text().split()
    assert listed and all("/vhdl/" not in p for p in listed)


def test_bad_prefix_is_refused_before_building():
    for prefix in ("9x", "a__", ""):
        out = OUT / "bad_prefix"
        result = subprocess.run(
            [
                sys.executable,
                str(COMPILER),
                str(DESIGN),
                "--comb",
                "--no_synth",
                "--module_prefix",
                prefix,
                "--out_dir",
                str(out),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        assert result.returncode != 0, prefix
        assert "--module_prefix" in result.stdout and "VHDL identifier" in result.stdout
        assert not (out / "vhdl_files.txt").exists()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir")
    args = parser.parse_args()
    OUT = Path(args.out_dir or tempfile.mkdtemp(prefix="module_prefix_"))
    OUT.mkdir(parents=True, exist_ok=True)
    from _test_main import run_module_tests

    run_module_tests()
