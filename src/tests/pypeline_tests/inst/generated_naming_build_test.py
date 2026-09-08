#!/usr/bin/env python3
"""Compare fresh-process VHDL and verify names with a real VHDL compiler."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
COMPILER = HERE.parents[2] / "pypelinec"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir")
    args = parser.parse_args()
    root = Path(args.out_dir or tempfile.mkdtemp(prefix="generated_naming_"))
    outputs = []
    for seed in ("1", "42"):
        out = root / seed
        subprocess.run(
            [
                sys.executable,
                str(COMPILER),
                str(HERE / "interface_factory_two_widths_test.py"),
                "--no_synth",
                "--out_dir",
                str(out),
            ],
            env={**os.environ, "PYTHONHASHSEED": seed},
            check=True,
        )
        files = {p.relative_to(out): p.read_bytes() for p in out.rglob("*.vhd")}
        assert files
        assert all(
            len(part.encode()) <= 240 for p in files for part in p.parts
        ), files.keys()
        outputs.append(files)
        index = (out / "name_index.log").read_text()
        for section in (
            "SOURCE DESCRIPTIONS",
            "INSTANCES AND WIRES",
            "EMITTED IDENTIFIERS",
            "PIPELINE VARIANTS",
        ):
            assert section in index, section
        package = (out / "c_structs_pkg.pkg.vhd").read_text()
        assert "kept_data_bus_t_from_kept_data_bus_n_4_data_t_uint8_t" in package
        assert "kept_data_bus_t_from_kept_data_bus_n_8_data_t_uint8_t" in package
        assert "-- Python:" in package and "-- Specialization:" in package
        for data in files.values():
            text = data.decode()
            for entity in re.findall(r"(?im)^entity\s+(\w+)\s+is", text):
                assert entity in index or entity.startswith(
                    ("top", "pipelinec_")
                ), entity
        work = out / "ghdl_work"
        work.mkdir()
        subprocess.run(
            ["ghdl", "-i", "--std=08", "-Wno-hide", "--workdir=" + str(work)]
            + [str(out / p) for p in files],
            cwd=str(work),
            check=True,
        )
        top = next((out / "top").glob("*.vhd")).stem
        subprocess.run(
            ["ghdl", "-m", "--std=08", "-Wno-hide", "--workdir=" + str(work), top],
            cwd=str(work),
            check=True,
        )
    assert (
        outputs[0] == outputs[1]
    ), "Fresh processes must emit identical paths and VHDL bytes"
    print("Generated names, source index, repeatability and GHDL elaboration PASS")


if __name__ == "__main__":
    main()
