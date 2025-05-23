#!/usr/bin/env python3

# Parse .bin files output from commands like
#   riscv32-unknown-elf-objcopy -O binary main text.bin --only-section .text
# into VHDL array of u32 init string

import sys
import struct


# VHDL doesnt accept DECIMAL 32b unsigned value constants
# since sees as signed 33b integer w/sign bit=0
# so instead explictly convert 32b unsigned to 32b signed
# Thanks https://stackoverflow.com/questions/24563786/conversion-from-hex-to-signed-dec-in-python
def s32(value):
    return -(value & 0x80000000) | (value & 0x7FFFFFFF)


in_file = sys.argv[1]

fin = open(in_file, "rb")
name = in_file.strip(".bin")

four_bytes = fin.read(4)
word_count = 0
s = f'#define {name}_MEM_INIT "(\\n\\\n'
while len(four_bytes) == 4:
    word_count += 1
    LITTLE_END_INTEGER = "<i"
    the_int = struct.unpack(LITTLE_END_INTEGER, four_bytes)[0]
    word_str = f"unsigned(to_signed({str(s32(the_int))}, 32))"
    word_str += ",\\n\\\n"
    s += word_str
    four_bytes = fin.read(4)

s += "others => (others => '0')\\n\\\n"
s += ')"\n'
# s += f'#define MEM_INIT_SIZE {word_count*4}\n'
with open(name + "_mem_init.h", "w") as of:
    of.write(s)
