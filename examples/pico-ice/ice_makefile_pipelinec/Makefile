# Example command lines:
#  # Export common env variables for all targets, ex.
#  # If running from outside the PipelineC repo examples, need to know path
#  export PIPELINEC_REPO=/media/1TB/Dropbox/PipelineC/git/PipelineC;
#  # Always need path to ghdl yosys nextpnr etc
#  export OSS_CAD_SUITE=/media/1TB/Programs/Linux/oss-cad-suite
#
#  PICO ICE:
#    # The basic 'top' design, see top.c, same as PIPELINEC_TOP_FILE=top.c default
#    make clean all
#    # Pong demo, see pong_top.c
#    make clean all PIPELINEC_TOP_FILE=pong_top.c
#
#    # Ethernet demo, see ethernet_top.c
#    make clean all PIPELINEC_TOP_FILE=eth/ethernet_top.c PLL_CLK_MHZ=16.0 NEXTPNR_ARGS="--pre-pack eth/eth_clocks.py"
#
#    # I2S RX to Ethernet TX demo, PLL produces I2S MCLK, see i2s_rx_eth_tx_top.c.c
#    make clean all PIPELINEC_TOP_FILE=i2s_rx_eth_tx/i2s_rx_eth_tx_top.c PLL_CLK_MHZ=22.579 NEXTPNR_ARGS="--pre-pack i2s_rx_eth_tx/i2s_rx_eth_tx_clocks.py"
#
#    # RISC-V Demo, see risc-v_top.c
#    #   First run 'make hex' in ./risc-v/firmware to build software/firmware for RISC-V CPU. This will be embedded into the risc-v cpu gateware
#    #   after the gateware is flashed to the pico-ice you can try uart echo demo in action (green led should be blinking all the time). If you are in linux use "screen /dev/ttyACM1 115200" 
#    make clean all PIPELINEC_TOP_FILE=risc-v/risc-v_top.c PLL_CLK_MHZ=16.0
#
#    # Program the FPGA. This applies to all the demos
#    make prog_pico
#
#  PICO2 ICE:
#    # The basic 'top' design, see top.c, same as PIPELINEC_TOP_FILE=top.c default
#    make clean all BOARD=PICO2
#    #   ^etc same commands as pico-ice, just append new BOARD=PICO2 argument
#    # Program the FPGA
#    make prog_pico2
YOSYS = $(OSS_CAD_SUITE)/bin/yosys
NEXTPNR = $(OSS_CAD_SUITE)/bin/nextpnr-ice40
ICEPACK = $(OSS_CAD_SUITE)/bin/icepack
ICEPLL = $(OSS_CAD_SUITE)/bin/icepll
DFU_UTIL = $(OSS_CAD_SUITE)/bin/dfu-util
BIN2UF2 = bin2uf2
PIPELINEC_REPO ?= $(realpath ../../../)
PIPELINEC = $(PIPELINEC_REPO)/src/pipelinec
TOP_NAME ?= top
PIPELINEC_TOP_FILE ?= $(TOP_NAME).c
SV_TOP_FILE ?= $(TOP_NAME).sv
BOARD ?= PICO # or PICO2

# Only one PLL producing one clock in design for now...
PLL_CLK_MHZ ?= 25.0
# Default nextpnr targetting the PLL clock freq
NEXTPNR_FREQ ?= $(PLL_CLK_MHZ)
NEXTPNR_ARGS ?= --freq $(NEXTPNR_FREQ)

all: pipelinec gateware.bin

clean:
	$(RM) lextab.py
	$(RM) yacctab.py
	$(RM) pipelinec_makefile_config.h
	$(RM) -r pipelinec_output
	$(RM) pipelinec.log
	$(RM) pll.v
	$(RM) *.json *.asc *.bin *.uf2
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
	$(YOSYS) -q -m ghdl -p "ghdl --std=08 -frelaxed `cat pipelinec_output/vhdl_files.txt` -e pipelinec_top; read_verilog -sv $(SV_TOP_FILE) pll.v; synth_ice40 -top $(TOP_NAME) -json $*.json" 2> yosys_stderr.log
	$(NEXTPNR) -q --seed 0 --up5k --package sg48 --pcf ice40.pcf --json $*.json --asc $*.asc $(NEXTPNR_ARGS)
	$(ICEPACK) $*.asc $@

.bin.uf2:
	$(BIN2UF2) -o $@ $<

# Cant invoke pipelinec with preprocessor macros set
# https://github.com/JulianKemmerer/PipelineC/issues/56
# So instead echo a .h file right before running tool...
pipelinec:
	echo "#define PLL_CLK_MHZ $(PLL_CLK_MHZ)\n" > pipelinec_makefile_config.h
	echo "#define BOARD_$(BOARD)\n" >> pipelinec_makefile_config.h
	$(PIPELINEC) $(PIPELINEC_TOP_FILE) --top pipelinec_top --out_dir pipelinec_output --comb --no_synth > pipelinec.log

.SUFFIXES: .v .sv .asc .bin .uf2
