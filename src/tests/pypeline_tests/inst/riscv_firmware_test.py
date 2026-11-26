"""Build each pinned ISA test and inspect RV32I linker, loader and input contracts."""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest import TestCase, mock

# Match the library search path installed by the design driver.
ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "include/pypeline")]
import pypeline
from riscv import firmware
from riscv.isa_tests import ISA_TESTS, RISCV_TESTS_DIR, INCLUDES
from riscv.toolchain import find_gcc
from cpu.mem_map import DMEM_BASE_ADDR
from cpu.sim_ctrl import TOHOST


def isa_image(name):
    return firmware.build(
        [RISCV_TESTS_DIR / "isa" / (name + ".S")],
        4096,
        1024,
        includes=INCLUDES,
        bootstrap=False,
    )


def test_all_integer_tests_fit():
    start = time.perf_counter()
    assert len(ISA_TESTS) == 40
    for name in ISA_TESTS:
        fw = isa_image(name)
        assert len(fw.imem_init) == 1024 and fw.imem_init[0]
        assert len(fw.dmem_init) == 256
    print(
        f"Mean firmware build and load: {(time.perf_counter() - start) / len(ISA_TESTS):.4f} s"
    )


def test_two_imports_produce_identical_words():
    assert isa_image("rv32ui/lw") == isa_image("rv32ui/lw")


def test_declared_dependencies_are_external_inputs():
    gcc = find_gcc(os.environ.get("RISCV_GCC"))
    with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
        pypeline._declared_files, clear=True
    ):
        source = Path(tmp) / "driver's program.c"
        header = Path(tmp) / "my header.h"
        header.write_text("#include <stdint.h>\n")
        source.write_text('#include "my header.h"\nint main(void) {return 0;}\n')
        firmware.build([source], 1024, 128)
        # Ask the preprocessor independently for transitive toolchain headers.
        rule = subprocess.check_output(
            [gcc, "-march=rv32i", "-mabi=ilp32", "-M", "-x", "c", "-"],
            input="#include <stdint.h>\n",
            text=True,
        )
        system = set(rule.replace("\\\n", " ").split(":", 1)[1].split())
        assert system and set(pypeline.DECLARED_FILES()) == system | {
            str(source),
            str(header),
        }


def test_each_translation_unit_declares_its_headers():
    with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
        pypeline._declared_files, clear=True
    ):
        root = Path(tmp)
        sources = [root / name for name in ("part.c", "main.c")]
        header = root / "part.h"
        header.write_text("#define VALUE 0\n")
        sources[0].write_text('#include "part.h"\nint part(void) {return VALUE;}\n')
        sources[1].write_text("int part(void); int main(void) {return part();}\n")
        firmware.build(sources, 256, 128)
        assert set(pypeline.DECLARED_FILES()) == {
            str(path) for path in sources + [header]
        }


def test_linker_symbols_and_dmem_sections():
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "main.c"
        source.write_text(
            "const unsigned table = 0x89abcdef; volatile unsigned counter;\n"
            "int main(void) {return counter;}\n"
        )
        gcc = Path(find_gcc(os.environ.get("RISCV_GCC")))
        nm = subprocess.check_output(
            [str(gcc), "-print-prog-name=nm"], text=True
        ).strip()
        build_image = firmware._image
        symbols = {}

        def inspect(data, windows, symbol):
            path = Path(tmp) / "image.elf"
            path.write_bytes(data)
            for line in subprocess.check_output(
                [nm, str(path)], text=True
            ).splitlines():
                value, _, name = line.split()
                symbols[name] = int(value, 16)
            return build_image(data, windows, symbol)

        with mock.patch.object(firmware, "_image", inspect):
            fw = firmware.build((source,), 1024, 128)
        assert (
            symbols["_bootstrap"] == 0 and symbols["__stacktop"] == DMEM_BASE_ADDR + 128
        )
        assert symbols["tohost"] == TOHOST and "__global_pointer$" not in symbols
        assert symbols["__bss_start"] <= symbols["counter"] < symbols["_end"]
        assert fw.dmem_init[(symbols["counter"] - DMEM_BASE_ADDR) // 4] == 0
        assert fw.dmem_init[(symbols["table"] - DMEM_BASE_ADDR) // 4] == 0x89ABCDEF


def test_entry_must_be_reset_vector():
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "start.S"
        source.write_text(
            ".section .text.init\n.word 0\n.globl _start\n_start: j _start\n"
        )
        with TestCase().assertRaisesRegex(ValueError, "entry _start at 0x00000004"):
            firmware.build([source], 128, 128, bootstrap=False)


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
