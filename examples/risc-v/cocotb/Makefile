
SIM ?= ghdl
EXTRA_ARGS += --std=08

TOPLEVEL_LANG ?= vhdl

#VERILOG_SOURCES += $(PWD)/my_design.sv
# use VHDL_SOURCES for VHDL files
# GHDL "@file" response file, not $(shell cat ...): a large VHDL file list
# inlined into cocotb's single-line "analyse" recipe can exceed Linux's
# MAX_ARG_STRLEN (131072 bytes per argv/envp string).
PIPELINEC_VHDL_FILES_TXT = $(HOME)/pipelinec_output/vhdl_files.txt
VHDL_SOURCES += @$(PIPELINEC_VHDL_FILES_TXT)
.PHONY: @$(PIPELINEC_VHDL_FILES_TXT)
CUSTOM_COMPILE_DEPS += $(PIPELINEC_VHDL_FILES_TXT)

# TOPLEVEL is the name of the toplevel module in your Verilog or VHDL file
TOPLEVEL = top

# MODULE is the basename of the Python test file
MODULE = test_top

# include cocotb's make rules to take care of the simulator setup
include $(shell cocotb-config --makefiles)/Makefile.sim
      
