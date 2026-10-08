# Example command lines:
#  # Always need the path to ghdl yosys nextpnr etc, ex.
#  export OSS_CAD_SUITE=/path/to/oss-cad-suite
#  # Only needed if this directory is copied outside the PipelineC repo
#  export PIPELINEC_REPO=/path/to/PipelineC
#
#  PICO ICE:
#    # The blinky design, see top.py (same as PYPELINE_TOP_FILE=top.py default)
#    make clean all
#    # VGA test pattern on PMOD0+PMOD1, see vga_top.py
#    make clean all PYPELINE_TOP_FILE=vga_top.py
#    # Program the FPGA, applies to all designs
#    make prog_pico
#
#  PICO2 ICE:
#    # Same build commands as pico-ice, then program the FPGA
#    make prog_pico2
YOSYS = $(OSS_CAD_SUITE)/bin/yosys
NEXTPNR = $(OSS_CAD_SUITE)/bin/nextpnr-ice40
ICEPACK = $(OSS_CAD_SUITE)/bin/icepack
ICEPLL = $(OSS_CAD_SUITE)/bin/icepll
DFU_UTIL = $(OSS_CAD_SUITE)/bin/dfu-util
BIN2UF2 = bin2uf2
PIPELINEC_REPO ?= $(realpath ../../../)
PYPELINEC = $(PIPELINEC_REPO)/src/pypelinec
TOP_NAME ?= top
PYPELINE_TOP_FILE ?= $(TOP_NAME).py
SV_TOP_FILE ?= $(TOP_NAME).sv

# Only one PLL producing one clock in design for now...
PLL_CLK_MHZ ?= 25.0
# Default nextpnr targetting the PLL clock freq
NEXTPNR_FREQ ?= $(PLL_CLK_MHZ)
NEXTPNR_ARGS ?= --freq $(NEXTPNR_FREQ)

all: pypeline gateware.bin

clean:
	$(RM) -r pypeline_output
	$(RM) pypelinec.log
	$(RM) pll.v
	$(RM) *.json *.asc *.bin *.uf2 yosys_build.ys
	$(RM) yosys_stderr.log
	$(RM) dfu_util.log
	$(RM) mpremote.log

prog_pico: gateware.bin
	sudo $(DFU_UTIL) -d 1209:b1c0 -a 1 -D gateware.bin -R > dfu_util.log

# pip3 install mpremote if needed
prog_pico2: gateware.bin
	mpremote cp gateware.bin : > mpremote.log
	mpremote run pico2_program_ice.py >> mpremote.log

gateware.bin: $(SV_TOP_FILE)
	$(ICEPLL) -q -i 12 -o $(PLL_CLK_MHZ) -p -m -f pll.v
	{ printf 'ghdl --std=08 -frelaxed '; cat pypeline_output/vhdl_files.txt; printf ' -e pypeline_top\n'; } > yosys_build.ys
	echo 'read_verilog -sv $(SV_TOP_FILE) pll.v' >> yosys_build.ys
	echo 'synth_ice40 -top $(TOP_NAME) -json $*.json' >> yosys_build.ys
	$(YOSYS) -q -m ghdl -s yosys_build.ys 2> yosys_stderr.log
	$(NEXTPNR) -q --seed 0 --up5k --package sg48 --pcf ice40.pcf --json $*.json --asc $*.asc $(NEXTPNR_ARGS)
	$(ICEPACK) $*.asc $@

.bin.uf2:
	$(BIN2UF2) -o $@ $<

# Pypeline design -> VHDL files listed in pypeline_output/vhdl_files.txt
pypeline:
	$(PYPELINEC) $(PYPELINE_TOP_FILE) --top pypeline_top --out_dir pypeline_output --comb --no_synth -D PLL_CLK_MHZ=$(PLL_CLK_MHZ) > pypelinec.log

.SUFFIXES: .v .sv .asc .bin .uf2
