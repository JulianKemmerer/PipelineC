"""Build RV32I firmware during design import and supply initialized RAM words.

The PipelineC firmware recipe credits MicroRV32's basic-c linker and Makefile:
https://github.com/agra-uni-bremen/microrv32/tree/master/microrv32/sw/basic-c
"""

import os
import re
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import NamedTuple

from pypeline import depends_on, param
from cpu.elf import load_elf
from cpu.mem_map import AddressMap
from riscv.toolchain import FALLBACK, GCC, find_gcc

# A top or the environment can select an installed toolchain.
RISCV_GCC = param(
    "RISCV_GCC", "", env="RISCV_GCC", help="RISC-V bare-metal gcc executable"
)


# Code generation flags, shared by the build and its dependency scan.
_CFLAGS = ["-march=rv32i", "-mabi=ilp32", "-O2"]


class Firmware(NamedTuple):
    imem_init: list
    dmem_init: list


def _image(data, windows, symbol):
    # PT_LOAD virtual addresses determine word offsets in the two RAM images.
    entry, words = load_elf(data, windows, e_machine=243)
    reset_vector = windows[0][0]
    if entry != reset_vector:
        raise ValueError(
            f"entry {symbol} at {entry:#010x} must equal reset vector {reset_vector:#010x}"
        )
    return Firmware(*words)


def load(path, imem_size, dmem_size, *, layout=AddressMap()):
    """Declare a prebuilt ELF and return its RAM images."""
    return _image(
        depends_on(Path(path)).read_bytes(),
        layout.memory_windows(imem_size=imem_size, dmem_size=dmem_size),
        "(_bootstrap or _start)",
    )


def _linker_script(imem_size, dmem_size, entry, layout):
    # Explicit load segments keep ELF headers and page padding outside RAM,
    # including when a relocated window starts in the middle of a page.
    # Loads use the data port, so even read-only C objects belong in DMEM.
    return f"""OUTPUT_ARCH("riscv")
ENTRY({entry})
PHDRS
{{
  code PT_LOAD FLAGS(5);
  data PT_LOAD FLAGS(6);
}}
MEMORY
{{
  imem (rx) : ORIGIN = 0x{layout.imem_base:08x}, LENGTH = {imem_size}
  dmem (rw) : ORIGIN = 0x{layout.dmem_base:08x}, LENGTH = {dmem_size}
}}
SECTIONS
{{
  .text : {{ KEEP(*(.text.init)) *(.text .text.*) }} > imem :code
  .rodata : {{ *(.rodata .rodata.*) *(.srodata .srodata.*) }} > dmem :data
  .data : {{ *(.data .data.*) *(.sdata .sdata.*) }} > dmem :data
  .bss (NOLOAD) : ALIGN(4) {{
    __bss_start = .;
    *(.sbss .sbss.*) *(.bss .bss.*) *(COMMON)
    . = ALIGN(4);
    _end = .;
  }} > dmem :data
  tohost = 0x{layout.tohost:08x};
  __stacktop = ORIGIN(dmem) + LENGTH(dmem);
}}
"""


# Startup shared by import-time compilation and stand-alone firmware projects.
_BOOTSTRAP = """\
.section .text.init
.globl _bootstrap
_bootstrap:
    # The stack grows down from the end of DMEM.
    la sp, __stacktop
    # A reset preserves RAM. Clear .bss on every entry.
    la t0, __bss_start
    la t1, _end
1:  bgeu t0, t1, 2f
    sw zero, 0(t0)
    addi t0, t0, 4
    j 1b
    # Call C with an initialized stack and zero-initialized globals.
2:  call main
    # Report main's return value using the riscv-tests exit convention.
    slli a0, a0, 1
    ori a0, a0, 1
    sw a0, tohost, t5
    # Remain here if the device leaves the CPU running.
3:  j 3b
"""


def _write_if_changed(path, content):
    data = content.encode()
    if path.is_file() and path.read_bytes() == data:
        return
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        try:
            tmp.write(data)
            tmp.close()
            os.replace(tmp.name, path)
        finally:
            if os.path.exists(tmp.name):
                os.unlink(tmp.name)


def _makefile(command):
    # Recipe arguments pass through both make's dollar expansion and the shell.
    def recipe(argv):
        return shlex.join(argv).replace("$", "$$")

    # Use the compiler driver's own binutils, including with a renamed gcc.
    gcc = command[0]
    lines = [
        ".PHONY: all dump-code dump-elf dump-comment",
        "",
        "all:",
        "\t" + recipe(command),
    ]
    for target, tool, flags in (
        ("dump-code", "objdump", ["-d", "-Mnumeric,no-aliases"]),
        ("dump-elf", "readelf", ["-a"]),
        ("dump-comment", "objdump", ["-s", "--section", ".comment"]),
    ):
        lookup = recipe([gcc, "-print-prog-name=" + tool])
        lines.extend(
            [
                "",
                target + ": all",
                '\t"$$(' + lookup + ')" ' + recipe(flags + ["fw.elf"]),
            ]
        )
    return "\n".join(lines) + "\n"


def build(
    sources,
    imem_size,
    dmem_size,
    *,
    includes=(),
    bootstrap=True,
    project_dir=None,
    layout=AddressMap(),
):
    """Compile sources in a private directory and declare gcc's actual inputs."""
    windows = layout.memory_windows(imem_size=imem_size, dmem_size=dmem_size)
    gcc = find_gcc(RISCV_GCC)
    if not gcc:
        raise RuntimeError(
            f"set RISCV_GCC to an executable or install {GCC} on PATH or at {FALLBACK}"
        )
    sources = [str(Path(s).absolute()) for s in sources]
    if not sources:
        raise ValueError("firmware build needs at least one source")
    entry = "_bootstrap" if bootstrap else "_start"
    linker = _linker_script(
        imem_size=imem_size, dmem_size=dmem_size, entry=entry, layout=layout
    )
    command = [gcc] + _CFLAGS + ["-nostdlib", "-nostartfiles", "-T", "link.ld", "-MD"]
    include_flags = ["-I" + str(Path(i).absolute()) for i in includes]
    command += include_flags
    if bootstrap:
        command.append("bootstrap.S")
    command += sources + ["-lgcc", "-o", "fw.elf"]
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        (directory / "link.ld").write_text(linker)
        if bootstrap:
            (directory / "bootstrap.S").write_text(_BOOTSTRAP)
        proc = subprocess.run(command, cwd=tmp, capture_output=True, text=True)
        if proc.returncode:
            raise RuntimeError(f"firmware gcc failed:\n{proc.stderr}")
        # With -o, -MD names the dependency file after the output, so every
        # source of one compile-and-link command writes fw.d and only the last
        # source's list survives. Scan the earlier sources with the same flags.
        for i, source in enumerate(sources[:-1]):
            dep = subprocess.run(
                [gcc]
                + _CFLAGS
                + ["-M", "-MF", f"input{i}.d"]
                + include_flags
                + [source],
                cwd=tmp,
                capture_output=True,
                text=True,
            )
            if dep.returncode:
                raise RuntimeError(f"firmware dependency scan failed:\n{dep.stderr}")
        inputs = set(map(Path, sources))
        for depfile in directory.glob("*.d"):
            rule = depfile.read_text().replace("\\\n", " ").split(":", 1)[1]
            # Make prerequisites use backslash-escaped whitespace and #, and
            # double dollar signs. Quotes in filenames are ordinary characters.
            for token in re.findall(r"(?:\\[ \t#\\]|[^ \t\n])+", rule):
                name = re.sub(r"\\([ \t#\\])", r"\1", token).replace("$$", "$")
                path = (directory / name).absolute()
                if directory not in path.parents:
                    inputs.add(path)
        for path in sorted(inputs):
            depends_on(path)
        image = _image((directory / "fw.elf").read_bytes(), windows, entry)
    # Export the same recipe and linker inputs that produced the embedded image.
    if project_dir is not None:
        project = Path(project_dir)
        project.mkdir(parents=True, exist_ok=True)
        _write_if_changed(project / "link.ld", linker)
        if bootstrap:
            _write_if_changed(project / "bootstrap.S", _BOOTSTRAP)
        _write_if_changed(project / "Makefile", _makefile(command))
    return image
