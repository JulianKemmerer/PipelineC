"""Compare generated Makefile firmware to import-built words, then boot its ELF."""

import argparse
import subprocess
import sys
from pathlib import Path

from built_hardware_sim_test import pypelinec

# The plain Python runner loads the same firmware library as the hardware top.
ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "include/pypeline")]
from riscv import firmware


def test_makefile_and_prebuilt_elf(root):
    example = ROOT / "examples/pypeline/riscv"
    export = root / "export"
    source = example / "main.c"
    built = firmware.build([source], 1024, 2048, project_dir=export)
    files = [export / n for n in ("Makefile", "link.ld", "bootstrap.S")]
    times = [p.stat().st_mtime_ns for p in files]
    subprocess.run(["make"], cwd=export, check=True)
    elf = export / "fw.elf"
    assert firmware.load(elf, 1024, 2048) == built
    log = pypelinec(
        example / "top.py",
        root / "sim",
        "--sim",
        "--comb",
        "--run",
        "all",
        "-D",
        "FIRMWARE=" + str(elf),
    )
    assert "TOHOST code=1 return_value=0" in log
    firmware.build([source], 1024, 2048, project_dir=export)
    assert [p.stat().st_mtime_ns for p in files] == times


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", type=Path, required=True)
    test_makefile_and_prebuilt_elf(parser.parse_args().out_dir)
