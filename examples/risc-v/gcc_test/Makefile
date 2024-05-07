# Thanks for the fantastic help from: 
# https://github.com/agra-uni-bremen/microrv32/blob/master/microrv32/sw/basic-c/Makefile
# export PATH=$PATH:/opt/riscv/bin

# Warning -O3 made frame animation stop? Like was never writing next frame to ram? TODO...sigh...
# SANTIY -O2
all : main.c bootstrap.S
	riscv32-unknown-elf-gcc  bootstrap.S main.c -o main -march=rv32i -mabi=ilp32 -mstrict-align -nostartfiles -Wl,--no-relax,--no-warn-rwx-segments -T link.ld
	
dump-elf: all
	riscv32-unknown-elf-readelf -a main
	
dump-code: all
	# numeric and no-aliases so use plain register numbers and no pseudo instruction names
	riscv32-unknown-elf-objdump -D main -Mnumeric -Mno-aliases
	
dump-comment: all
	objdump -s --section .comment main

hex: all
	./elf2bin.py main mem_init.h
    
clean:
	rm -f main

.PHONY: all sim dump-elf dump-code dump-comment hex clean
