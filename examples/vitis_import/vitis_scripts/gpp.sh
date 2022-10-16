 #!/bin/bash
mkdir -p o

g++ -c \
    -I${XILINX_XRT}/include \
    -D__USE_XOPEN2K8 \
    -o o/main.o sources/main.cpp
g++ -c \
    -I${XILINX_XRT}/include \
    -D__USE_XOPEN2K8 \
    -o o/xcl2.o includes/xcl2.cpp

g++ -Wall \
    -o main o/*.o \
    -lxilinxopencl \
    -lxrt_coreutil \
    -lpthread \
    -lrt \
    -lstdc++ \
    -L${XILINX_XRT}/lib