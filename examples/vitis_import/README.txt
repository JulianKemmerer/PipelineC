Source Xilinx env first!

If you wish to use HW-emu for now you must comment float_pkg from VHDL sources...
Change TARGET to "HW_EMU"
and run test:
export XCL_EMULATION_MODE=hw_emu
./main kernel.xclbin
