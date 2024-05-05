#!/usr/bin/env python3

# Script to write out a memory initialization file from an elf 

# Thanks for the fantastic help from: 
# https://github.com/agra-uni-bremen/microrv32/blob/master/microrv32/sw/elf2bin.py
from elftools.elf.elffile import ELFFile
import sys, itertools
from collections import namedtuple
import binascii

in_file = sys.argv[1]
out_file = sys.argv[2]
if len(sys.argv) == 4:
	# parse third argument as memory size given in hex (0xabc)
	MEM_SIZE_IN_BYTES = int(sys.argv[3],16)
else:
	MEM_SIZE_IN_BYTES = 4*1024
	print(f"Using {MEM_SIZE_IN_BYTES} bytes ({int(MEM_SIZE_IN_BYTES/4)} 32b words) default size for mem_size")

Section = namedtuple("Section", ["header", "data"])

class AddressSpace:
	def __init__(self, left, right):
		self.left = left
		self.right = right
		assert right > left
		diff = right - left
		assert diff % 4 == 0
		self.data = diff*[0]
		
	def load(self, sec):
		dst = sec.header.p_paddr - self.left
		assert dst >= 0
		
		for i,x in enumerate(sec.data):
			self.data[dst+i] = x

# VHDL doesnt accept DECIMAL 32b unsigned value constants
# since sees as signed 33b integer w/sign bit=0
# so instead explictly convert 32b unsigned to 32b signed
# Thanks https://stackoverflow.com/questions/24563786/conversion-from-hex-to-signed-dec-in-python
def s32(value):
    return -(value & 0x80000000) | (value & 0x7fffffff)

with open(in_file, 'rb') as f:
	##print("> process: {}".format(in_file))
	ef = ELFFile(f)
	load = []
	null = []
	for x in ef.iter_segments():
		h = x.header
		if h.p_type == "PT_LOAD":
			load.append(Section(h, x.data()))
		if h.p_type == "PT_NULL":
			null.append(Section(h, x.data()))
			
	if len(load) == 0:
		raise RuntimeError("no load section")
			
	left = None
	right = None
	for x,d in itertools.chain(load, null):
		if left is None:
			left = x.p_paddr
		else:
			left = min(left, x.p_paddr)
			
		if right is None:
			right = x.p_paddr + x.p_memsz
		else:
			right = max(right, x.p_paddr + x.p_memsz)

	mem = AddressSpace(left, right)
	for x in itertools.chain(load, null):
		mem.load(x)

	with open(out_file, "w") as of:
		bytes = list(mem.data)
		bytes.extend((MEM_SIZE_IN_BYTES - len(bytes))*[0])
		if len(bytes) > MEM_SIZE_IN_BYTES:
			raise RuntimeError("executable does not fit into memory -- len:" + str(len(bytes)))
		# reformat so it represents how its loaded in memory as 32b words
		s = '#define MEM_INIT "(\\n\\\n'
		i = 0
		while i < len(bytes):
			word_hex = ""
			for _ in range(4):
				byte_str = "{:02X}".format(bytes[i])
				word_hex = byte_str + word_hex
				i += 1
			word_int = int(word_hex, 16)
			word_str = f"unsigned(to_signed({str(s32(word_int))}, 32))"
			if i!=len(bytes):
				word_str += ",\\n\\\n"
			s += word_str
		s += ')"\n'
		s += f'#define MEM_INIT_SIZE {MEM_SIZE_IN_BYTES}\n'
		of.write(s)
