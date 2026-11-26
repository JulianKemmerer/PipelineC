"""Three sky130 builds (cold, edited C, edited header) and one up-to-date check."""

import argparse
import shutil
from pathlib import Path

from built_hardware_sim_test import pypelinec

# Small RAMs still hold the demo code, globals and stack.
BUILD_ARGS = (
    "--comb",
    "--syn_tool",
    "device_models",
    "-D",
    "IMEM_SIZE=576",
    "-D",
    "DMEM_SIZE=128",
)


def test_firmware_edits_invalidate_build(root):
    example = Path(__file__).resolve().parents[4] / "examples/pypeline/riscv"
    design = Path(shutil.copy(example / "top.py", root))
    source = root / "main.c"
    header = root / "seed.h"
    header.write_text("#define SEED 12345\n")
    source.write_text(
        '#include "seed.h"\n'
        + (example / "main.c").read_text().replace("= 12345;", "= SEED;")
    )
    hw = root / "hardware"
    pypelinec(design, hw, *BUILD_ARGS)
    assert "Up to date: " in pypelinec(design, hw, *BUILD_ARGS)
    for path, old, new in ((source, "i < 100", "i < 99"), (header, "12345", "12346")):
        content = path.read_text()
        assert old in content
        path.write_text(content.replace(old, new))
        log = pypelinec(design, hw, *BUILD_ARGS)
        assert f"Building again: {path} changed since the build in" in log


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out_dir", type=Path, required=True)
    test_firmware_edits_invalidate_build(parser.parse_args().out_dir)
