# Makefile based on https://github.com/ulx3s/blink/blob/main/Makefile
.ONESHELL: # Applies to every targets in the file!

PYFILES = lextab.py yacctab.py
DIR = output/pipelinec_top

all: build prog
	
build:
	../../../src/pipelinec apsk_demo.c --top pipelinec_top --out_dir output
	cp pll.v $(DIR)
	cp top.v $(DIR)

apsk_demo.json:
	cd $(DIR)
	echo  -n "yosys -m ghdl  -p 'ghdl --std=08 -frelaxed " > build.sh
	cat ../vhdl_files.txt >> build.sh
	echo "-e pipelinec_top; read_verilog top.v; synth_ecp5 -abc9 -nowidelut -json apsk_demo.json' > ../yosyslog.log " >> build.sh
	bash build.sh

ulx3s.bit: ulx3s_out.config
	cd $(DIR)
	ecppack ulx3s_out.config ulx3s.bit

ulx3s_out.config: apsk_demo.json
	cd $(DIR)
	nextpnr-ecp5 --85k --json apsk_demo.json \
		--pre-pack ../clocks.py --seed 1 \
		--lpf ../../ulx3s_v20.lpf \
		--textcfg ulx3s_out.config \
		--package CABGA381

prog: ulx3s.bit
	cd $(DIR)
	fujprog ulx3s.bit

clean:
	rm -rf output rm ulx3s_out.config ulx3s.bit $(PYFILES)