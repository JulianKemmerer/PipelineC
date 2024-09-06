# Thanks for the fantastic help from: 
# https://github.com/agra-uni-bremen/microrv32/blob/master/microrv32/sw/basic-c/Makefile
# export PATH=$PATH:/opt/riscv/bin

all : main.c bootstrap.S
	# Stack size needs to match linker script? use larger than warning of 1/4 stack size?
	riscv32-unknown-elf-gcc -O3 bootstrap.S main.c -lm -o main -march=rv32im -mabi=ilp32 -mstrict-align -nostartfiles -Wl,--no-relax,--no-warn-rwx-segments,-z stack-size=32768 -Wlarger-than=8196 -T link.ld
	
dump-elf: all
	riscv32-unknown-elf-readelf -a main
	
dump-code: all
	# numeric and no-aliases so use plain register numbers and no pseudo instruction names
	riscv32-unknown-elf-objdump -D main -Mnumeric -Mno-aliases
	
dump-comment: all
	objdump -s --section .comment main

hex: all
	riscv32-unknown-elf-objcopy -O binary main text.bin --only-section .text
	./bin2vhdl.py text.bin
	riscv32-unknown-elf-objcopy -O binary main data.bin --only-section .data
	./bin2vhdl.py data.bin
	
clean:
	rm -f main

.PHONY: all sim dump-elf dump-code dump-comment hex clean
