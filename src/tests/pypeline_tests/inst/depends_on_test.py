#!/usr/bin/env python3
"""A file the design's import declares with pypeline.depends_on is a build
input like its Python sources (PY_TO_LOGIC.DESIGN_SOURCE_HASHES,
SIM.BUILT_HARDWARE_IS_CURRENT, SIM.SIMULATE_BUILT_HARDWARE). One sky130 build
of depends_on_rom_design.py, whose ROM words come from words.txt, then:

- test_build_records_the_declared_file: built_hardware.json and
  source_provenance.json list words.txt with its hash;
- test_identical_build_is_up_to_date: the same build again does nothing and
  leaves the out_dir unchanged;
- test_testbench_refuses_an_edited_file: a native testbench of the built
  hardware reads the built word, then refuses to run once words.txt changed;
- test_edited_file_builds_again: the next build names words.txt as changed
  (a second, warm build) and the built ROM holds the new word;
- test_missing_file_stops_the_import: the failing run names words.txt.

Two small sky130 builds, an up-to-date run, two native runs (one refused) and
one failing run.
"""

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from built_hardware_sim_test import pypelinec, snapshot

BUILD_ARGS = ("--syn_tool", "device_models", "--pipeline_min_effort", "0")


def built_rom(hw):
    """The VHDL of the one ROM entity the build synthesized."""
    paths = (hw / "vhdl_files.txt").read_text().split()
    roms = [Path(path) for path in paths if "_init_h" in Path(path).name]
    assert len(roms) == 1, roms
    return roms[0].read_bytes()


def test_build_records_the_declared_file(words, hw):
    sha = hashlib.sha256(words.read_bytes()).hexdigest()
    record = json.loads((hw / "built_hardware.json").read_text())
    assert record["sources"].get(str(words)) == sha, record["sources"]
    provenance = json.loads((hw / "source_provenance.json").read_text())
    entry = provenance["sources"].get(str(words))
    assert entry is not None and entry["sha256"] == sha and entry["declared"], entry
    print("test_build_records_the_declared_file PASS")


def test_identical_build_is_up_to_date(design, hw):
    before = snapshot(hw)
    log = pypelinec(design, hw, *BUILD_ARGS)
    assert "Up to date: " in log, "an unchanged declared file must not rebuild"
    assert "PY_TO_LOGIC parsing" not in log and "Synthesizing" not in log
    assert snapshot(hw) == before, "an up-to-date build must not write its out_dir"
    print("test_identical_build_is_up_to_date PASS")


def test_testbench_refuses_an_edited_file(tb, words, hw):
    before = snapshot(hw)
    log = pypelinec(tb, hw, "--sim", "--run", "1")
    assert "ROM word: 1" in log, "the testbench must read the built word"
    words.write_text("6 2 3 4")
    log = pypelinec(tb, hw, "--sim", "--run", "1", check=False)
    assert "these sources changed since that build" in log and str(words) in log
    assert "ROM word:" not in log, "the refused testbench must not simulate"
    assert snapshot(hw) == before, "simulating built hardware must not write its out_dir"
    print("test_testbench_refuses_an_edited_file PASS")


def test_edited_file_builds_again(design, words, hw):
    assert b'0 => "00000001"' in built_rom(hw)
    assert words.read_text() == "6 2 3 4", "set by test_testbench_refuses_an_edited_file"
    log = pypelinec(design, hw, *BUILD_ARGS)
    assert f"Building again: {words} changed since the build in" in log, log
    assert b'0 => "00000110"' in built_rom(hw), "the build must use the edited word"
    print("test_edited_file_builds_again PASS")


def test_missing_file_stops_the_import(design, words, hw):
    words.unlink()
    log = pypelinec(design, hw, *BUILD_ARGS, check=False)
    assert "Up to date: " not in log
    assert "FileNotFoundError" in log and str(words) in log, log
    print("test_missing_file_stops_the_import PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", type=Path, required=True)
    root = parser.parse_args().out_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    for name in ("depends_on_rom_design.py", "depends_on_rom_tb_design.py"):
        shutil.copy(Path(__file__).with_name(name), root / name)
    design = root / "depends_on_rom_design.py"
    tb = root / "depends_on_rom_tb_design.py"
    words = root / "words.txt"
    words.write_text("1 2 3 4")
    hw = root / "hardware"
    pypelinec(design, hw, *BUILD_ARGS)
    test_build_records_the_declared_file(words, hw)
    test_identical_build_is_up_to_date(design, hw)
    test_testbench_refuses_an_edited_file(tb, words, hw)
    test_edited_file_builds_again(design, words, hw)
    test_missing_file_stops_the_import(design, words, hw)
