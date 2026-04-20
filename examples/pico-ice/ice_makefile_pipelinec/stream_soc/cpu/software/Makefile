# Thanks for the fantastic help from: 
# https://github.com/agra-uni-bremen/microrv32/blob/master/microrv32/sw/basic-c/Makefile
# export PATH=$PATH:/opt/riscv/bin

PIPELINEC_REPO ?= $(realpath ../../../../../../)
PIPELINEC_INCLUDE?=$(PIPELINEC_REPO)/include
CFLAGS?=-I$(PIPELINEC_INCLUDE)

all : main.c bootstrap.S
	riscv32-unknown-elf-gcc -O3 bootstrap.S main.c -lm -o main -Wpadded -Werror=padded -march=rv32i -mabi=ilp32 -mstrict-align -nostartfiles -T link.ld $(CFLAGS)
	
dump-elf: all
	riscv32-unknown-elf-readelf -a main
	
dump-code: all
	# numeric and no-aliases so use plain register numbers and no pseudo instruction names
	riscv32-unknown-elf-objdump -D main -Mnumeric -Mno-aliases
	
dump-comment: all
	objdump -s --section .comment main

hex: all
	riscv32-unknown-elf-objcopy -O binary main text.bin --only-section .text
	$(PIPELINEC_INCLUDE)/risc-v/bin2vhdl.py text.bin
	riscv32-unknown-elf-objcopy -O binary main data.bin --only-section .data
	$(PIPELINEC_INCLUDE)/risc-v/bin2vhdl.py data.bin
	#cp *_mem_init.h ../hardware/
	
clean:
	rm -f main text.bin data.bin
	rm -f ../hardware/text_mem_init.h ../hardware/data_mem_init.h

.PHONY: all sim dump-elf dump-code dump-comment hex clean