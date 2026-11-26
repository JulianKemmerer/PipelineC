"""RISC-V gcc discovery shared with the test runner (no HDL imports)."""

import shutil
from pathlib import Path

# Upstream bare-metal compiler and the conventional local install.
GCC = "riscv32-unknown-elf-gcc"
# Installation used when the cross compiler is absent from PATH.
FALLBACK = Path("/opt/riscv/bin") / GCC


def find_gcc(explicit=""):
    """Resolve RISCV_GCC, or search PATH then the default installation."""
    for candidate in (explicit, GCC, str(FALLBACK)):
        path = candidate and shutil.which(candidate)
        if path:
            return str(Path(path).absolute())
    return None
