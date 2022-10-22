 #!/bin/bash
#VITIS_PLATFORM=xilinx_u50_gen3x16_xdma_5_202210_1
#export XCL_EMULATION_MODE=hw_emu
#emconfigutil --nd 1  --platform ${VITIS_PLATFORM} --od .
./main kernel.xclbin
