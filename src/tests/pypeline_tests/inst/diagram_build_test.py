#!/usr/bin/env python3
"""The design diagram (diagram.html, src/DIAGRAM.py) that pypelinec builds
write into --out_dir, checked against what the build itself recorded.

One sky130 build of built_hardware_top_design.py (an AUTO_PIPELINE region the
100 MHz goal cuts, an AUTO_FSM), then:

- test_diagram_latencies_match_built_hardware: MAIN latencies and the
  AUTO_PIPELINE call site's latency equal built_hardware.json's;
- test_measured_delays_are_recorded: functions carry the delays the build
  measured, and the pipelined region's offsets are the compiler's own
  zero-added-clocks pipeline map: each call site spans its callee's delay,
  starting no earlier than 0;
- test_no_synth_build_writes_structure: a --no_synth build of the same top in
  a second out_dir writes a diagram with the same MAINs and links and no
  delays;
- test_failed_build_removes_old_diagram: a build of a broken top in the first
  out_dir fails after removing the diagram the first build wrote.

One synthesizing build, one --no_synth build and one failing parse. The build
passes --pipeline_min_effort 0 for the reason built_hardware_sim_test.py gives
(issue 45).
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
FIXTURES = ("built_hardware_core_design.py", "built_hardware_top_design.py")
CORE = "built_hardware_core_design"
BODY_SITE_FUNC = f"{CORE}_body_main"


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


def diagram(out_dir):
    html = (out_dir / "diagram.html").read_text()
    start = html.index('id="design">') + len('id="design">')
    return json.loads(html[start : html.index("</script>", start)])


def body_site(data):
    """The AUTO_PIPELINE call site's instance name in the body MAIN."""
    g = data["funcs"][BODY_SITE_FUNC]["graph"]
    (node,) = [n for n in g["nodes"] if n.get("auto_pipeline") == "built_hardware_body"]
    return node, BODY_SITE_FUNC + "____" + node["id"][2:]


def test_diagram_latencies_match_built_hardware(hw):
    record = json.loads((hw / "built_hardware.json").read_text())
    data = diagram(hw)
    assert {m: e["latency"] for m, e in data["mains"].items()} == record[
        "main_latencies"
    ]
    body = record["auto_pipeline_latencies"]["built_hardware_body"]
    assert body > 0, "the 100 MHz goal should cut the divide on sky130"
    _node, inst = body_site(data)
    assert data["inst_latency"][inst] == body, (data["inst_latency"], body)
    print("test_diagram_latencies_match_built_hardware PASS")


def test_measured_delays_are_recorded(hw):
    data = diagram(hw)
    assert data["build"]["tool"] == "DEVICE_MODELS"
    node, _inst = body_site(data)
    divide = data["funcs"][node["callee"]]
    assert divide["delay_ns"] > 0, divide.get("delay_ns")
    offsets = divide["offsets"]
    callee = {
        n["id"][2:]: n["callee"] for n in divide["graph"]["nodes"] if n["kind"] == "sub"
    }
    assert offsets and set(offsets) <= set(callee), (sorted(offsets), sorted(callee))
    for local, (start, end) in offsets.items():
        # The map composes the callees' own delays (a measured whole-function
        # delay can be smaller: synthesis optimizes across them)
        delay = data["funcs"][callee[local]]["delay_ns"]
        assert start >= 0 and abs(end - start - delay) < 0.15, (
            local,
            start,
            end,
            delay,
        )
    assert max(end for _s, end in offsets.values()) > 0
    print("test_measured_delays_are_recorded PASS")


def test_no_synth_build_writes_structure(designs, hw, root):
    other = root / "no_synth"
    pypelinec(designs / "built_hardware_top_design.py", other, "--no_synth")
    built, plain = diagram(hw), diagram(other)
    assert sorted(plain["mains"]) == sorted(built["mains"])
    assert plain["links"] == built["links"]
    assert plain["build"]["delays_known"] == 0, plain["build"]
    assert all("offsets" not in f for f in plain["funcs"].values())
    print("test_no_synth_build_writes_structure PASS")


def test_failed_build_removes_old_diagram(designs, hw):
    assert (hw / "diagram.html").exists()
    broken = designs / "broken_top_design.py"
    broken.write_text(
        (designs / "built_hardware_top_design.py").read_text()
        + "\n\n@MAIN(core.GOAL_MHZ)\ndef broken_main():\n    body_out_port = no_such_name\n"
    )
    log = pypelinec(broken, hw, "--syn_tool", "device_models", check=False)
    assert "no_such_name" in log
    assert not (
        hw / "diagram.html"
    ).exists(), "a failed build must not leave the old diagram"
    print("test_failed_build_removes_old_diagram PASS")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir")
    args = parser.parse_args()
    root = Path(args.out_dir or tempfile.mkdtemp(prefix="diagram_build_"))
    designs = root / "designs"
    designs.mkdir(parents=True, exist_ok=True)
    for name in FIXTURES:
        shutil.copy(HERE / name, designs / name)
    hw = root / "hw"
    pypelinec(
        designs / "built_hardware_top_design.py",
        hw,
        "--syn_tool",
        "device_models",
        "--pipeline_min_effort",
        "0",
    )
    test_diagram_latencies_match_built_hardware(hw)
    test_measured_delays_are_recorded(hw)
    test_no_synth_build_writes_structure(designs, hw, root)
    test_failed_build_removes_old_diagram(designs, hw)


if __name__ == "__main__":
    main()
