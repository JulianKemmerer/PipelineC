# Program the FPGA on the first board Vivado's hardware server finds with board.bit
# (volatile: lost at power off). Run from this directory, ex.
#   vivado -mode batch -source program.tcl
open_hw_manager
connect_hw_server
open_hw_target
set device [lindex [get_hw_devices xc7a*] 0]
current_hw_device $device
set_property PROGRAM.FILE board.bit $device
program_hw_devices $device
close_hw_target
disconnect_hw_server
close_hw_manager
