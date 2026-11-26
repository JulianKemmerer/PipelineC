"""Place ELF32 little-endian PT_LOAD segments in CPU memory windows."""

import struct


def load_elf(data, windows, e_machine):
    """Return (entry address, lists of uint32 words) in the given window order."""
    if len(data) < 52 or data[:6] != b"\x7fELF\x01\x01":
        raise ValueError("expected a 32-bit little-endian ELF")
    machine, _, entry, phoff = struct.unpack_from("<HIII", data, 18)
    phentsize, phnum = struct.unpack_from("<HH", data, 42)
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
            "<6I", data, phoff + index * phentsize
        )
        if kind != 1:
            continue
        segment = f"segment {index} at 0x{addr:08x}, {memsz} bytes"
        if filesz > memsz or (filesz and offset + filesz > len(data)):
            raise ValueError(f"{segment}: invalid file extent ({filesz} bytes)")
        if not memsz:
            continue
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
