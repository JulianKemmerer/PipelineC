#!/usr/bin/env python3
"""Design parameters through the drivers (pypelinec, pypeline_sim.py):
  - -D WIDTH=16 / STEP=3 changes the generated VHDL (port width, constant);
    the build prints the parameter table and records it in
    source_provenance.json;
  - --list_params lists declarations without elaborating;
  - a value outside choices= and a misspelled -D name fail the build with a
    one-line reason;
  - cpp-style injected globals (no param()) reach module-level code and a
    hardware body;
  - native simulation sees -D values, both from pypeline_sim.py and from
    pypelinec --sim --comb;
  - a sky130 build that re-elaborates (pin-and-confirm pass 2) imports the
    design with identical values in every pass, and reports the bottom-up
    values each pass read vs built, with where they were read, on stdout and
    in sweep_history.json "latency_passes".
In-process details (types, precedence, checks) are design_params_test.py."""
import argparse
import json
import os
import re
import subprocess
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(THIS_DIR, "..", "..", ".."))
PYPELINEC = os.path.join(SRC, "pypelinec")
PYPELINE_SIM = os.path.join(SRC, "pypeline_sim.py")
DESIGN = os.path.join(THIS_DIR, "design_params_design.py")
INJECTED = os.path.join(THIS_DIR, "design_params_injected_design.py")
SIM_DESIGN = os.path.join(THIS_DIR, "design_params_sim_design.py")
PASS2_DESIGN = os.path.join(THIS_DIR, "design_params_pass2_design.py")


def run(cmd, expect_ok=True):
    print("Running:", " ".join(cmd), flush=True)
    result = subprocess.run(
        [sys.executable] + cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    print(result.stdout[-4000:], flush=True)
    assert (result.returncode == 0) == expect_ok, (cmd, result.returncode)
    return result.stdout


def vhdl_text(out_dir):
    text = ""
    for dirpath, _, files in os.walk(out_dir):
        for name in files:
            if name.endswith(".vhd"):
                with open(os.path.join(dirpath, name)) as f:
                    text += f.read()
    return text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", required=True)
    out = parser.parse_args().out_dir

    # -D changes the hardware, and the build reports where each value came from
    default_dir, set_dir = os.path.join(out, "default"), os.path.join(out, "set")
    run([PYPELINEC, DESIGN, "--comb", "--no_synth", "--out_dir", default_dir])
    log = run([PYPELINEC, DESIGN, "--comb", "--no_synth", "--out_dir", set_dir,
               "-D", "WIDTH=16", "--define", "STEP=3"])
    assert "design_params_main_x : in unsigned(7 downto 0)" in vhdl_text(default_dir)
    assert "design_params_main_x : in unsigned(15 downto 0)" in vhdl_text(set_dir)
    assert "to_unsigned(3," in vhdl_text(set_dir)
    assert re.search(r"Design parameters:\n  GOAL_MHZ = 100\.0 \(default\)", log), log
    assert "WIDTH    = 16 (-D)" in log
    with open(os.path.join(set_dir, "source_provenance.json")) as f:
        recorded = {r["name"]: r for r in json.load(f)["design_params"]}
    assert recorded["WIDTH"]["value"] == 16 and recorded["WIDTH"]["source"] == "-D"
    assert recorded["GOAL_MHZ"]["source"] == "default"

    # --list_params: declarations only, no elaboration
    listing = run([PYPELINEC, DESIGN, "--list_params", "-D", "STEP=2"])
    assert "WIDTH: int = 8 (default); one of 8, 12, 16" in listing, listing
    assert "STEP: int = 2 (-D)" in listing and "data path width in bits" in listing
    assert "elaborating func" not in listing

    # Bad values and names fail with a reason, before any elaboration
    bad = run([PYPELINEC, DESIGN, "--no_synth", "--out_dir", os.path.join(out, "bad"),
               "-D", "WIDTH=10"], expect_ok=False)
    assert "Design parameter WIDTH: 10 is not one of (8, 12, 16) (from -D on the command line" in bad
    typo = run([PYPELINEC, DESIGN, "--no_synth", "--out_dir", os.path.join(out, "typo"),
                "-D", "WIDHT=16"], expect_ok=False)
    assert "-D WIDHT: nothing in this design uses it" in typo and "Did you mean WIDTH?" in typo

    # Injected globals: module level and inside a hardware body
    injected_dir = os.path.join(out, "injected")
    log = run([PYPELINEC, INJECTED, "--comb", "--no_synth", "--out_dir", injected_dir,
               "-D", "INJ_WIDTH=12", "-D", "INJ_INC=3"])
    assert "INJ_INC   = 3 (injected)" in log
    assert "design_params_injected_main_x : in unsigned(11 downto 0)" in vhdl_text(injected_dir)
    assert "to_unsigned(3," in vhdl_text(injected_dir)

    # Native simulation sees the values, from either driver
    expected = [f"DESIGN_PARAMS_SIM count={c} STEP=2 TAG=7" for c in (0, 2, 4, 6)]
    for cmd in (
        [PYPELINE_SIM, SIM_DESIGN, "--run", "all", "-D", "STEP=2", "-D", "TAG=7"],
        [PYPELINEC, SIM_DESIGN, "--sim", "--comb", "--run", "all", "--out_dir",
         os.path.join(out, "sim"), "-D", "STEP=2", "-D", "TAG=7"],
    ):
        lines = [l.strip() for l in run(cmd).splitlines() if l.startswith("DESIGN_PARAMS_SIM")]
        assert lines == expected, lines

    # Re-elaboration: every pass imports the design with the same values
    log = run([PYPELINEC, PASS2_DESIGN, "--syn_tool", "device_models", "--out_dir",
               os.path.join(out, "pass2"), "-D", "START=1", "-D", "TAG=5"])
    imports = [l for l in log.splitlines() if l.startswith("DESIGN_PARAMS_IMPORT")]
    assert "AUTO_PIPELINE Pass 2" in log, "fixture no longer re-elaborates"
    assert len(imports) >= 2 and set(imports) == {"DESIGN_PARAMS_IMPORT START=1 TAG=5"}, imports

    # The bottom-up report: what pass 1 read (the start_latency=1 seed) vs built
    assert "Bottom-up values read during pass 1 elaboration (read -> built):" in log
    assert "<- differs" in log and "=> converged: every read matches what was built" in log
    with open(os.path.join(out, "pass2", "top", "sweep_history.json")) as f:
        history = json.load(f)
    assert history["schema_version"] == 4
    passes = history["latency_passes"]
    assert passes[0]["pass"] == 1 and passes[0]["reads"][0]["read"] == [1]
    assert not passes[0]["reads"][0]["matches"] and passes[-1]["outcome"].startswith("converged")
    with open(PASS2_DESIGN) as f:
        direct_line = next(n for n, l in enumerate(f, 1) if "# DIRECT_LATENCY_READ" in l)
    sites = passes[0]["reads"][0]["read_at"]
    assert f"{PASS2_DESIGN}:{direct_line}" in sites, sites
    assert any("stream_auto_pipeline.py:" in s and f"(via {PASS2_DESIGN}:" in s for s in sites), sites
    print("All design parameter driver tests passed.")


if __name__ == "__main__":
    main()
