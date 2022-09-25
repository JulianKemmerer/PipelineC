#!/usr/bin/env python3

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
	MEM_SIZE_IN_BYTES = 512
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
		s = ""
		i = 0
		while i < len(bytes):
			word_str = ""
			for _ in range(4):
				byte_str = "{:02X}".format(bytes[i])
				word_str = byte_str + word_str
				i += 1 
			word_str = "0x" + word_str 
			if i!=len(bytes):
				word_str += ",\n"
			s += word_str
		of.write(s)
