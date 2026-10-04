# Vivado non-project build: Pypeline generated VHDL + board.vhd + arty.xdc -> board.bit
# Run from this directory after pypelinec has written ./pypeline_output, ex.
#   vivado -mode batch -source build.tcl -tclargs xc7a35ticsg324-1L
# (The Makefile does both steps.)
set part [lindex $argv 0]
if {$part eq ""} { set part xc7a35ticsg324-1L }

# Pypeline generated VHDL (written by pypelinec for Xilinx parts)
source pypeline_output/read_vhdl.tcl
# Board wrapper and pin constraints
read_vhdl -vhdl2008 board.vhd
read_xdc arty.xdc

synth_design -top board -part $part
opt_design
place_design
route_design

report_utilization -file utilization.rpt
report_timing_summary -file timing_summary.rpt
write_bitstream -force board.bit
