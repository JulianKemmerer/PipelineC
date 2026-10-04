# Example command lines:
#  # Only needed if this directory is copied outside the PipelineC repo
#  export PIPELINEC_REPO=/path/to/PipelineC
#  # vivado must be on the PATH, or pass VIVADO=/path/to/Vivado/<version>/bin/vivado
#
#  # Build board.bit for the Arty A7-35T, see top.py
#  make clean all
#  # Arty A7-100T (also switch top.py to import board.arty.part100t)
#  make clean all PART=xc7a100tcsg324-1
#  # Program the FPGA over USB
#  make prog
PIPELINEC_REPO ?= $(realpath ../../../)
PYPELINEC = $(PIPELINEC_REPO)/src/pypelinec
PYPELINE_TOP_FILE ?= top.py
VIVADO ?= vivado
PART ?= xc7a35ticsg324-1L

all: pypeline board.bit

clean:
	$(RM) -r pypeline_output .Xil
	$(RM) pypelinec.log vivado*.log vivado*.jou
	$(RM) board.bit utilization.rpt timing_summary.rpt

# Pypeline design -> VHDL files and pypeline_output/read_vhdl.tcl
pypeline:
	$(PYPELINEC) $(PYPELINE_TOP_FILE) --out_dir pypeline_output --comb --no_synth > pypelinec.log

board.bit: board.vhd arty.xdc
	$(VIVADO) -mode batch -nojournal -log vivado.log -source build.tcl -tclargs $(PART)

prog: board.bit
	$(VIVADO) -mode batch -nojournal -log vivado_prog.log -source program.tcl
