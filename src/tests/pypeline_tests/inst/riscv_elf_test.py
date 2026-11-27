"""Exercise ELF segment placement and precise failures without a toolchain."""

import struct
import sys
from pathlib import Path
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "include/pypeline"))
from riscv.firmware import load_elf


def elf(addr, data, memsz):
    header = struct.pack(
        "<16sHHIIIIIHHHHHH",
        b"\x7fELF\x01\x01",
        2,
        243,
        1,
        4,
        52,
        0,
        0,
        52,
        32,
        1,
        0,
        0,
        0,
    )
    segment = struct.pack("<8I", 1, 84, addr, 0, len(data), memsz, 0, 4)
    return header + segment + data


def read(data):
    return load_elf(data=data, windows=[(0, 8), (32, 8)], e_machine=243)


def test_placement_uses_virtual_address():
    entry, images = read(elf(33, b"\x01\x02\x03\x04", 4))
    assert entry == 4 and images == [[0, 0], [0x03020100, 4]]


def test_zero_fill_to_memory_size():
    assert read(elf(0, b"abc", 8))[1][0] == [0x636261, 0]


def test_disjoint_noload_is_ignored():
    assert read(elf(64, b"", 4))[1] == [[0, 0], [0, 0]]


def test_outside_window_names_segment():
    with TestCase().assertRaisesRegex(
        ValueError, "segment 0 at 0x00000040, 2 bytes.*outside"
    ):
        read(elf(64, b"x", 2))


def test_overflow_names_segment():
    for addr in (7, 31):
        with TestCase().assertRaisesRegex(
            ValueError, f"segment 0 at {addr:#010x}, 2 bytes.*overflows"
        ):
            read(elf(addr, b"", 2))


def test_rejected_inputs():
    data = elf(0, b"a", 4)
    for bad in (
        b"",
        data[:4],
        b"NOPE" + data[4:],
        data[:4] + b"\x02" + data[5:],
        data[:5] + b"\x02" + data[6:],
        data[:18] + bytes(2) + data[20:],
        data[:60],
        data[:-1],
        elf(0, b"abc", 1),
    ):
        with TestCase().assertRaises(ValueError):
            read(bad)


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
