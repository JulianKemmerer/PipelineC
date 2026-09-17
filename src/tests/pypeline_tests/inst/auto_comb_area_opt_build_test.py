"""Real RTL equivalence and mapped-area checks for combinational HLS."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

SRC = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SRC))
import C_TO_LOGIC  # establish the backend's existing import order
import OPEN_TOOLS

CORE = """
from pypeline import *
@hw_func
def core(a:uint8_t,b:uint8_t,c:uint8_t,d:uint8_t,s:uint1_t)->uint16_t:
    x:uint16_t = a*b
    y:uint16_t = c*d
    return x if s else y
AREA_OPT = AUTO_COMB_AREA_OPT(core)
"""


def run(cmd, cwd, env=None):
    result = subprocess.run([str(x) for x in cmd], cwd=str(cwd), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if result.returncode:
        raise AssertionError(f"{cmd!r} failed:\n{result.stdout[-9000:]}")
    return result.stdout


def build(path, source):
    path.mkdir(parents=True, exist_ok=True)
    design = path / "design.py"
    design.write_text(source)
    # sky130 (DEVICE_MODELS) is the suite's fast synthesis tool; the RTL
    # checks below run their own yosys and don't depend on it.
    run([sys.executable, SRC / "pypelinec", design, "--comb", "--syn_tool", "sky130",
         "--out_dir", path], path)
    return (path / "vhdl_files.txt").read_text()


def yosys(path, files, commands):
    script = path / "check.ys"
    script.write_text("\n".join([f"ghdl --std=08 {files} -e top", "hierarchy -top top"] + commands))
    env = dict(os.environ, GHDL_PREFIX=OPEN_TOOLS.GHDL_PREFIX)
    cmd = [Path(OPEN_TOOLS.YOSYS_BIN_PATH) / "yosys"]
    cmd += shlex.split(OPEN_TOOLS.GET_GHDL_PLUGIN_FLAGS()) + ["-s", script]
    output = run(cmd, path, env)
    (path / "yosys_check.log").write_text(output)
    return output


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out_dir", required=True)
    args = ap.parse_args()
    root = Path(args.out_dir)
    proof = root / "proof"
    source = CORE + """
@MAIN(1.0)
def proof(a:uint8_t,b:uint8_t,c:uint8_t,d:uint8_t,s:uint1_t)->uint1_t:
    return core(a,b,c,d,s) == AREA_OPT(a,b,c,d,s)
"""
    files = build(proof, source)
    output = yosys(proof, files, ["flatten", "proc", "opt",
        "sat -verify -prove proof_return_output 1 -show-inputs -show-outputs"])
    assert "SUCCESS" in output, output[-4000:]
    print("PASS: bit-exact equivalence proved over all input combinations")
    counts = []
    for label, callee in (("original", "core"), ("area_opt", "AREA_OPT")):
        path = root / label
        files = build(path, CORE + f"""
@MAIN(1.0)
def design(a:uint8_t,b:uint8_t,c:uint8_t,d:uint8_t,s:uint1_t)->uint16_t:
    return {callee}(a,b,c,d,s)
""")
        yosys(path, files, ["synth -flatten -top top", "write_json mapped.json"])
        cells = json.loads((path / "mapped.json").read_text())["modules"]["top"]["cells"]
        assert not any(re.search(r"DFF|LATCH", cell["type"], re.I) for cell in cells.values())
        counts.append(len(cells))
    assert counts[1] < counts[0], counts
    print(f"PASS: mapped combinational cells {counts[0]} -> {counts[1]}, no registers")


if __name__ == "__main__":
    main()
