"""Pinned integer ISA tests shared by the design and its test registrations."""

from pathlib import Path

# Assembly wrappers include their matching rv64ui source by relative path.
RISCV_TESTS_DIR = Path(__file__).parent / "riscv-tests"
# The trap-free header takes precedence over upstream environments.
TEST_ENV = Path(__file__).parent / "test_env"
# GCC include paths common to every integer test.
INCLUDES = (TEST_ENV, RISCV_TESTS_DIR / "isa/macros/scalar")
# These tests need architectural features outside the single-cycle core.
EXCLUDED = {
    "fence_i": "writes instruction memory",
    "ma_data": "misaligned data accesses",
}
# Parameter values include the upstream suite name, e.g. rv32ui/add.
ISA_TESTS = tuple(
    "rv32ui/" + path.stem
    for path in sorted((RISCV_TESTS_DIR / "isa/rv32ui").glob(pattern="*.S"))
    if path.stem not in EXCLUDED
)
