 #!/bin/bash
if [ $1 == "hw_emu" ]; then
    VITIS_PLATFORM=$2
    export XCL_EMULATION_MODE=$1
    emconfigutil --nd 1  --platform ${VITIS_PLATFORM} --od .
fi
./main kernel.xclbin
