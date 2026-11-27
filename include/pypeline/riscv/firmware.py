"""Build RV32I firmware during design import and supply initialized RAM words.

The PipelineC firmware recipe credits MicroRV32's basic-c linker and Makefile:
https://github.com/agra-uni-bremen/microrv32/tree/master/microrv32/sw/basic-c
"""

import os
import re
import shlex
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import NamedTuple

# Upstream bare-metal compiler and the conventional local install.
GCC = "riscv32-unknown-elf-gcc"
# Installation used when the cross compiler is absent from PATH.
FALLBACK = Path("/opt/riscv/bin") / GCC


def find_gcc(explicit=""):
    """Resolve RISCV_GCC, or search PATH then the default installation."""
    for candidate in (explicit, GCC, str(FALLBACK)):
        path = candidate and shutil.which(cmd=candidate)
        if path:
            return str(Path(path).absolute())
    return None


def load_elf(data, windows, e_machine):
    """Return (entry address, lists of uint32 words) in the given window order."""
    if len(data) < 52 or data[:6] != b"\x7fELF\x01\x01":
        raise ValueError("expected a 32-bit little-endian ELF")
    # ELF32 stores the machine, entry and program-header offset in the file
    # header. Only program headers describe the bytes loaded at runtime.
    machine, _, entry, phoff = struct.unpack_from("<HIII", buffer=data, offset=18)
    phentsize, phnum = struct.unpack_from("<HH", buffer=data, offset=42)
    if machine != e_machine:
        raise ValueError(f"ELF e_machine {machine}, expected {e_machine}")
    if phnum and (phentsize < 32 or phoff + phnum * phentsize > len(data)):
        raise ValueError("invalid ELF program header table")
    memories = []
    for base, size in windows:
        if size < 0 or size % 4:
            raise ValueError(f"window at {base:#x} needs a whole number of words")
        memories.append((base, bytearray(size)))
    for index in range(phnum):
        kind, offset, addr, _, filesz, memsz = struct.unpack_from(
            "<6I", buffer=data, offset=phoff + index * phentsize
        )
        if kind != 1:
            continue
        segment = f"segment {index} at 0x{addr:08x}, {memsz} bytes"
        if filesz > memsz or (filesz and offset + filesz > len(data)):
            raise ValueError(f"{segment}: invalid file extent ({filesz} bytes)")
        if not memsz:
            continue
        # A loadable segment must fit entirely in one physical RAM. The
        # bytes beyond its on-disk extent represent zero-initialized storage.
        for base, memory in memories:
            end = base + len(memory)
            if addr < end and addr + memsz > base:
                if addr < base or addr + memsz > end:
                    raise ValueError(f"{segment} overflows window at {base:#x}")
                start = addr - base
                memory[start : start + filesz] = data[offset : offset + filesz]
                memory[start + filesz : start + memsz] = bytes(memsz - filesz)
                break
        else:
            if filesz:  # A disjoint NOLOAD segment such as .tohost has no image.
                raise ValueError(f"{segment} lies outside the memory windows")
    return entry, [
        list(struct.unpack(f"<{len(mem) // 4}I", mem)) for _, mem in memories
    ]


# Code generation flags, shared by the build and its dependency scan.
_CFLAGS = ["-march=rv32i", "-mabi=ilp32", "-O2"]


class Firmware(NamedTuple):
    imem_init: list
    dmem_init: list


def _image(data, windows, symbol):
    # PT_LOAD virtual addresses determine word offsets in the two RAM images.
    entry, words = load_elf(data=data, windows=windows, e_machine=243)
    reset_vector = windows[0][0]
    if entry != reset_vector:
        raise ValueError(
            f"entry {symbol} at {entry:#010x} must equal reset vector {reset_vector:#010x}"
        )
    return Firmware(imem_init=words[0], dmem_init=words[1])


def load(*, path, layout):
    """Declare a prebuilt ELF and return its RAM images."""
    from pypeline import depends_on

    return _image(
        data=depends_on(path=Path(path)).read_bytes(),
        windows=layout.memory_windows(),
        symbol="(_bootstrap or _start)",
    )


def _linker_script(*, entry, layout):
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
  imem (rx) : ORIGIN = 0x{layout.imem_base:08x}, LENGTH = {layout.imem_size}
  dmem (rw) : ORIGIN = 0x{layout.dmem_base:08x}, LENGTH = {layout.dmem_size}
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
    # Readers of an exported project may run make while another build exports.
    # Replace complete files atomically and preserve timestamps on unchanged inputs.
    data = content.encode()
    if path.is_file() and path.read_bytes() == data:
        return
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        try:
            tmp.write(data)
            tmp.close()
            os.replace(src=tmp.name, dst=path)
        finally:
            if os.path.exists(tmp.name):
                os.unlink(path=tmp.name)


def _makefile(command):
    # Recipe arguments pass through both make's dollar expansion and the shell.
    def recipe(argv):
        return shlex.join(split_command=argv).replace("$", "$$")

    # Use the compiler driver's own binutils, including with a renamed gcc.
    gcc = command[0]
    lines = [
        ".PHONY: all dump-code dump-elf dump-comment",
        "",
        "all:",
        "\t" + recipe(argv=command),
    ]
    for target, tool, flags in (
        ("dump-code", "objdump", ["-d", "-Mnumeric,no-aliases"]),
        ("dump-elf", "readelf", ["-a"]),
        ("dump-comment", "objdump", ["-s", "--section", ".comment"]),
    ):
        lookup = recipe(argv=[gcc, "-print-prog-name=" + tool])
        lines.extend(
            [
                "",
                target + ": all",
                '\t"$$(' + lookup + ')" ' + recipe(argv=flags + ["fw.elf"]),
            ]
        )
    return "\n".join(lines) + "\n"


def build(
    *,
    sources,
    layout,
    includes=(),
    bootstrap=True,
    project_dir=None,
):
    """Compile sources in a private directory and declare gcc's actual inputs."""
    # Keep tool discovery and ELF inspection usable by the software-only
    # test runner. Only a design build registers HDL parameters and inputs.
    from pypeline import depends_on, param

    windows = layout.memory_windows()
    compiler = param(
        name="RISCV_GCC",
        default="",
        env="RISCV_GCC",
        help="RISC-V bare-metal gcc executable",
    )
    gcc = find_gcc(explicit=compiler)
    if not gcc:
        raise RuntimeError(
            f"set RISCV_GCC to an executable or install {GCC} on PATH or at {FALLBACK}"
        )
    sources = [str(Path(s).absolute()) for s in sources]
    if not sources:
        raise ValueError("firmware build needs at least one source")
    entry = "_bootstrap" if bootstrap else "_start"
    linker = _linker_script(entry=entry, layout=layout)
    command = [gcc] + _CFLAGS + ["-nostdlib", "-nostartfiles", "-T", "link.ld", "-MD"]
    include_flags = ["-I" + str(Path(i).absolute()) for i in includes]
    command += include_flags
    if bootstrap:
        command.append("bootstrap.S")
    command += sources + ["-lgcc", "-o", "fw.elf"]
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        (directory / "link.ld").write_text(data=linker)
        if bootstrap:
            (directory / "bootstrap.S").write_text(data=_BOOTSTRAP)
        proc = subprocess.run(args=command, cwd=tmp, capture_output=True, text=True)
        if proc.returncode:
            raise RuntimeError(f"firmware gcc failed:\n{proc.stderr}")
        # With -o, -MD names the dependency file after the output, so every
        # source of one compile-and-link command writes fw.d and only the last
        # source's list survives. Scan the earlier sources with the same flags.
        for i, source in enumerate(sources[:-1]):
            dep = subprocess.run(
                args=[gcc]
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
        for depfile in directory.glob(pattern="*.d"):
            rule = (
                depfile.read_text().replace("\\\n", " ").split(sep=":", maxsplit=1)[1]
            )
            # Make prerequisites use backslash-escaped whitespace and #, and
            # double dollar signs. Quotes in filenames are ordinary characters.
            for token in re.findall(pattern=r"(?:\\[ \t#\\]|[^ \t\n])+", string=rule):
                name = re.sub(
                    pattern=r"\\([ \t#\\])", repl=r"\1", string=token
                ).replace("$$", "$")
                path = (directory / name).absolute()
                if directory not in path.parents:
                    inputs.add(path)
        for path in sorted(inputs):
            depends_on(path=path)
        image = _image(
            data=(directory / "fw.elf").read_bytes(), windows=windows, symbol=entry
        )
    # Export the same recipe and linker inputs that produced the embedded image.
    if project_dir is not None:
        project = Path(project_dir)
        project.mkdir(parents=True, exist_ok=True)
        _write_if_changed(path=project / "link.ld", content=linker)
        if bootstrap:
            _write_if_changed(path=project / "bootstrap.S", content=_BOOTSTRAP)
        _write_if_changed(path=project / "Makefile", content=_makefile(command=command))
    return image
