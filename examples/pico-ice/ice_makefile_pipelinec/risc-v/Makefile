# Thanks for the fantastic help from: 
# https://github.com/agra-uni-bremen/microrv32/blob/master/microrv32/sw/basic-c/Makefile
# export PATH=$PATH:/opt/riscv/bin

# TODO make switchable between archs
# -march=rv32im

all : main.c bootstrap.S
	riscv32-unknown-elf-gcc -O3 bootstrap.S main.c -lm -o main -march=rv32i -mabi=ilp32 -mstrict-align -nostartfiles -T link.ld
	
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
	rm -f main text.bin data.bin text_mem_init.h data_mem_init.h

.PHONY: all sim dump-elf dump-code dump-comment hex clean
