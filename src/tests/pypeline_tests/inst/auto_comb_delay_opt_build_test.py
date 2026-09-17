"""SAT equivalence, register-free RTL, and mapped combinational timing."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

from auto_comb_area_opt_build_test import SRC, build, yosys


CORE = """
from pypeline import *
@hw_func
def core(a:uint4_t,b:uint4_t,c:uint4_t,d:uint4_t,s:uint1_t)->uint8_t:
    p:uint8_t=a*b
    choose:uint1_t=(p>c)^s
    left:uint4_t=a if choose else c
    right:uint4_t=b if choose else d
    return left*right
DELAY_OPT=AUTO_COMB_DELAY_OPT(core)
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", required=True)
    args = parser.parse_args()
    root = Path(args.out_dir)
    proof = root / "proof"
    files = build(proof, CORE + """
@MAIN(1.0)
def proof(a:uint4_t,b:uint4_t,c:uint4_t,d:uint4_t,s:uint1_t)->uint1_t:
    return core(a,b,c,d,s)==DELAY_OPT(a,b,c,d,s)
""")
    output = yosys(proof, files, ["flatten", "proc", "opt",
        "sat -verify -prove proof_return_output 1 -show-inputs -show-outputs"])
    assert "SUCCESS" in output
    print("PASS: DELAY_OPT equivalence proved for all inputs", flush=True)
    measurements = []
    for label, callee in (("original", "core"), ("delay_opt", "DELAY_OPT")):
        path = root / label
        source = CORE + f"""
PART("sky130")
@MAIN(1.0)
def design(a:uint4_t,b:uint4_t,c:uint4_t,d:uint4_t,s:uint1_t)->uint8_t:
    return {callee}(a,b,c,d,s)
"""
        files = build(path, source)
        yosys(path, files, ["synth -flatten -top top", "write_json mapped.json"])
        cells = json.loads((path / "mapped.json").read_text())["modules"]["top"]["cells"]
        assert not any(re.search(r"DFF|LATCH", cell["type"], re.I) for cell in cells.values())
        # Separate validation build: selection itself must never request these
        # extra synthesis jobs. Keep complete live logs on success or failure.
        with (path / "timing_build.log").open("w") as log:
            result = subprocess.run([sys.executable, str(SRC / "pypelinec"), str(path / "design.py"),
                                     "--out_dir", str(path / "timing")], stdout=log, stderr=subprocess.STDOUT)
        assert result.returncode == 0, str(path / "timing_build.log")
        history = json.loads((path / "timing/top/sweep_history.json").read_text())
        final = history["mains"]["design"]["final"]
        assert history["build_complete"] and final["met"], final
        assert final["achieved_mhz"] > 0 and not final["mhz_is_lower_bound"], final
        measurements.append({"variant": label, "mapped_cells": len(cells),
                             "measured_path_ns": 1000.0 / final["achieved_mhz"],
                             "timing_log": str(path / "timing_build.log")})
    (root / "measurements.json").write_text(json.dumps(measurements, indent=2))
    print("PASS: no core registers; separate sky130 timing builds completed", measurements, flush=True)


if __name__ == "__main__":
    main()
