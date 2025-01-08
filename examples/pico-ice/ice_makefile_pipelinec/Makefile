YOSYS = $(OSS_CAD_SUITE)/bin/yosys
NEXTPNR = $(OSS_CAD_SUITE)/bin/nextpnr-ice40
ICEPACK = $(OSS_CAD_SUITE)/bin/icepack
ICEPLL = $(OSS_CAD_SUITE)/bin/icepll
DFU_UTIL = $(OSS_CAD_SUITE)/bin/dfu-util
BIN2UF2 = bin2uf2
PIPELINEC = $(PIPELINEC_REPO)/src/pipelinec
PIPELINEC_TOP_FILE ?= top.c

# Only one PLL producing one clock in design for now...
PLL_CLK_MHZ = 25.0

all: pipelinec gateware.bin

clean:
	$(RM) lextab.py
	$(RM) yacctab.py
	$(RM) pll_clk_mhz.h
	$(RM) -r pipelinec_output
	$(RM) pipelinec.log
	$(RM) pll.v
	$(RM) *.json *.asc *.bin *.uf2
	$(RM) yosys_stderr.log
	$(RM) dfu_util.log

prog: gateware.bin
	sudo $(DFU_UTIL) -d 1209:b1c0 -a 1 -D gateware.bin -R > dfu_util.log

gateware.bin: top.sv
	$(ICEPLL) -q -i 12 -o $(PLL_CLK_MHZ) -p -m -f pll.v
	$(YOSYS) -q -m ghdl -p "ghdl --std=08 -frelaxed `cat pipelinec_output/vhdl_files.txt` -e pipelinec_top; read_verilog -sv top.sv pll.v; synth_ice40 -top top -json $*.json" 2> yosys_stderr.log
	$(NEXTPNR) -q --randomize-seed --up5k --package sg48 --pcf ice40.pcf --json $*.json --asc $*.asc --freq $(PLL_CLK_MHZ)
	$(ICEPACK) $*.asc $@

.bin.uf2:
	$(BIN2UF2) -o $@ $<

# Cant invoke pipelinec with preprocessor macros set
# https://github.com/JulianKemmerer/PipelineC/issues/56
# So instead echo a .h file right before running tool...
pipelinec:
	echo "#define PLL_CLK_MHZ $(PLL_CLK_MHZ)\n" > pll_clk_mhz.h
	$(PIPELINEC) $(PIPELINEC_TOP_FILE) --top pipelinec_top --out_dir pipelinec_output --comb --no_synth > pipelinec.log

.SUFFIXES: .v .sv .asc .bin .uf2
