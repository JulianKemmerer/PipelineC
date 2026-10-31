#!/usr/bin/env python3
"""Native simulation of a testbench on the hardware built for another top
(SIM.SIMULATE_BUILT_HARDWARE, SIM.WRITE_BUILT_HARDWARE), and the up-to-date
build that record makes possible (SIM.BUILT_HARDWARE_IS_CURRENT).

One sky130 build of built_hardware_top_design.py, whose real ports keep all of
built_hardware_core_design.py, then native --sim runs of
built_hardware_tb_design.py in that build's --out_dir:

- test_testbench_runs_on_the_built_latencies: no elaboration or synthesis,
  the out_dir is left unchanged, and results arrive after the built
  AUTO_PIPELINE depth and AUTO_FSM latency;
- test_undecided_tag_is_refused: -D EXTRA_TAG=1 reads the latency of a tag
  the build never decided;
- test_latency_the_build_read_but_never_built_is_served: the core design
  reads the .latency of a tag no MAIN instantiates, which a hints file seeds
  to SPARE_SEED, so the build reads that value; the testbench reads it too;
- test_tag_the_build_only_read_is_refused_when_called: -D CALL_SPARE=1;
- test_changed_design_parameter_is_refused;
- test_changed_source_is_refused;
- test_identical_build_is_up_to_date: the same build command again does
  nothing and leaves the out_dir unchanged;
- test_other_compilers_hardware_is_refused: in a copy of the out_dir, a record
  from another compiler version, or one with no build inputs, is refused;
- test_rebuild_builds: --rebuild builds again (warm) and rewrites the record;
- test_new_build_removes_the_record: a --no_synth build in that out_dir.

Two builds in all, plus the --no_synth one: the first, cold, and the warm
--rebuild. The fixtures are copied into the test's output directory first, so the
changed-source case can edit one. The build passes --pipeline_min_effort 0:
a trim trial of this design hits issue 45 (#381, a failed trim attributed to
MAINs that cannot be pipelined is kept).
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
COMPILER = HERE.parents[2] / "pypelinec"
FIXTURES = (
    "built_hardware_core_design.py",
    "built_hardware_top_design.py",
    "built_hardware_tb_design.py",
)
# Starting latency the hints file gives the tag the build reads but never
# builds: not its default 0, so the testbench can only see it from the record
SPARE_SEED = 2


def pypelinec(design, out_dir, *extra, check=True):
    """Run pypelinec, echo its output and return it."""
    run = subprocess.run(
        [sys.executable, str(COMPILER), str(design), "--out_dir", str(out_dir), *extra],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    print(run.stdout)
    if check:
        assert run.returncode == 0, f"{design.name} exited {run.returncode}"
    else:
        assert run.returncode != 0, f"{design.name} was expected to fail"
    return run.stdout


def simulate_tb(designs, hw, *extra, check=True):
    return pypelinec(
        designs / "built_hardware_tb_design.py", hw, "--sim", "--run", "all", *extra,
        check=check,
    )


def snapshot(directory):
    return {p: p.read_bytes() for p in sorted(directory.rglob("*")) if p.is_file()}


def test_testbench_runs_on_the_built_latencies(designs, hw):
    record = json.loads((hw / "built_hardware.json").read_text())
    body = record["auto_pipeline_latencies"]["built_hardware_body"]
    (fsm,) = record["auto_fsm_schedules"].values()
    assert body > 0, "the 100 MHz goal should cut the divide on sky130"
    before = snapshot(hw)
    log = simulate_tb(designs, hw)
    assert "Native sim: simulating the hardware built from" in log
    for marker in ("PY_TO_LOGIC parsing", "Synthesizing", "Running:"):
        assert marker not in log, f"the testbench run must not build: {marker!r}"
    assert snapshot(hw) == before, "simulating built hardware must not write its out_dir"
    # The body MAIN has no MAIN-level stages, so the region depth is the delay
    assert record["main_latencies"]["built_hardware_core_design_body_main"] == 0
    assert f"BODY.latency {body}" in log and f"region result after {body} cycles" in log
    assert f"OPS_FSM.latency {fsm['latency']}" in log
    assert f"FSM result after {fsm['latency']} cycles" in log
    print("test_testbench_runs_on_the_built_latencies PASS")


def test_undecided_tag_is_refused(designs, hw):
    log = simulate_tb(designs, hw, "-D", "EXTRA_TAG=1", check=False)
    assert "AUTO_PIPELINE built_hardware_extra is not part of the hardware built in" in log
    print("test_undecided_tag_is_refused PASS")


def test_latency_the_build_read_but_never_built_is_served(designs, hw):
    record = json.loads((hw / "built_hardware.json").read_text())
    assert "built_hardware_spare" not in record["auto_pipeline_latencies"]
    reads = record["unbuilt_latency_reads"]["AUTO_PIPELINE"]
    assert reads["built_hardware_spare"] == SPARE_SEED
    log = simulate_tb(designs, hw)
    assert f"SPARE.latency {SPARE_SEED}" in log
    print("test_latency_the_build_read_but_never_built_is_served PASS")


def test_tag_the_build_only_read_is_refused_when_called(designs, hw):
    log = simulate_tb(designs, hw, "-D", "CALL_SPARE=1", check=False)
    assert "AUTO_PIPELINE built_hardware_spare is not part of the hardware built in" in log
    print("test_tag_the_build_only_read_is_refused_when_called PASS")


def test_changed_design_parameter_is_refused(designs, hw):
    log = simulate_tb(designs, hw, "-D", "GOAL_MHZ=90", check=False)
    assert "design parameters differ from the hardware built in" in log
    assert "GOAL_MHZ=90 (built with 100)" in log
    print("test_changed_design_parameter_is_refused PASS")


def test_changed_source_is_refused(designs, hw):
    core = designs / "built_hardware_core_design.py"
    original = core.read_text()
    core.write_text(original + "# edited after the build\n")
    try:
        log = simulate_tb(designs, hw, check=False)
    finally:
        core.write_text(original)
    assert "sources changed since that build" in log and str(core) in log
    print("test_changed_source_is_refused PASS")


# Lines only a build prints: a run that prints none of them built nothing
BUILD_MARKERS = (
    "PY_TO_LOGIC parsing",
    "Synthesizing",
    "Running:",
    "Synthesis results:",
)


def test_identical_build_is_up_to_date(designs, hw, build_args):
    before = snapshot(hw)
    log = pypelinec(designs / "built_hardware_top_design.py", hw, *build_args)
    assert "Up to date: " in log and "holds the timing-met build of" in log
    for marker in BUILD_MARKERS:
        assert marker not in log, f"an up-to-date build must not build: {marker!r}"
    assert snapshot(hw) == before, "an up-to-date build must not write its out_dir"
    print("test_identical_build_is_up_to_date PASS")


def test_other_compilers_hardware_is_refused(designs, hw):
    other = hw.parent / "hw_other_compiler"
    shutil.copytree(hw, other)
    path = other / "built_hardware.json"
    record = json.loads(path.read_text())
    record["build_inputs"]["compiler"] = "another compiler version"
    path.write_text(json.dumps(record))
    log = simulate_tb(designs, other, check=False)
    assert "by another version of the compiler" in log
    # A record written before build inputs were recorded came from an older compiler
    del record["build_inputs"]
    path.write_text(json.dumps(record))
    log = simulate_tb(designs, other, check=False)
    assert "by another version of the compiler" in log
    print("test_other_compilers_hardware_is_refused PASS")


def test_rebuild_builds(designs, hw, build_args):
    path = hw / "built_hardware.json"
    before = json.loads(path.read_text())
    log = pypelinec(
        designs / "built_hardware_top_design.py", hw, *build_args, "--rebuild"
    )
    assert "Up to date:" not in log and "Synthesis results:" in log
    # Rewritten by the build that met timing, from the same inputs
    assert "Built hardware for native simulation of other tops" in log
    assert json.loads(path.read_text())["build_inputs"] == before["build_inputs"]
    print("test_rebuild_builds PASS")


def test_new_build_removes_the_record(designs, hw):
    pypelinec(designs / "built_hardware_top_design.py", hw, "--no_synth")
    assert not (hw / "built_hardware.json").exists()
    print("test_new_build_removes_the_record PASS")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir")
    args = parser.parse_args()
    root = Path(args.out_dir or tempfile.mkdtemp(prefix="built_hardware_sim_"))
    designs = root / "designs"
    designs.mkdir(parents=True, exist_ok=True)
    for name in FIXTURES:
        shutil.copy(HERE / name, designs / name)
    hints = designs / "hints.json"
    hints.write_text(json.dumps({"AUTO_PIPELINE": {"built_hardware_spare": SPARE_SEED}}))
    hw = root / "hw"
    build_args = (
        "--syn_tool",
        "device_models",
        "--pipeline_min_effort",
        "0",
        "--latency_hints",
        str(hints),
    )
    pypelinec(designs / "built_hardware_top_design.py", hw, *build_args)
    test_testbench_runs_on_the_built_latencies(designs, hw)
    test_undecided_tag_is_refused(designs, hw)
    test_latency_the_build_read_but_never_built_is_served(designs, hw)
    test_tag_the_build_only_read_is_refused_when_called(designs, hw)
    test_changed_design_parameter_is_refused(designs, hw)
    test_changed_source_is_refused(designs, hw)
    test_identical_build_is_up_to_date(designs, hw, build_args)
    test_other_compilers_hardware_is_refused(designs, hw)
    test_rebuild_builds(designs, hw, build_args)
    test_new_build_removes_the_record(designs, hw)


if __name__ == "__main__":
    main()
