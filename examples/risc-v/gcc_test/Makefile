# Thanks for the fantastic help from: 
# https://github.com/agra-uni-bremen/microrv32/blob/master/microrv32/sw/basic-c/Makefile
# export PATH=$PATH:/opt/riscv/bin

all : main.c bootstrap.S
	riscv32-unknown-elf-gcc bootstrap.S main.c -o main -march=rv32i -mabi=ilp32 -nostartfiles -Wl,--no-relax,--no-warn-rwx-segments -T link.ld 
	
sim: all
	riscv-vp --intercept-syscalls main
	
dump-elf: all
	riscv32-unknown-elf-readelf -a main
	
dump-code: all
	riscv32-unknown-elf-objdump -D main
	
dump-comment: all
	objdump -s --section .comment main

hex: all
	./elf2bin.py main mem.hex
    
clean:
	rm -f main

.PHONY: all sim dump-elf dump-code dump-comment hex clean