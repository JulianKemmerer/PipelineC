// Code wrapping the AXI4 (FPGA) and
// file (XDMA driver) abstractions to a common 'DMA message'

#pragma once
#include "../../uintN_t.h"

// Current DMA example requires:
// 	Minimum 64 bytes messages (1 cycle of aligned AXI4 512b data)
//    Maximum tested was 4096
//    Only tested sizes multiple of 64 bytes 
#define DMA_MSG_SIZE 65536 //8192 //4096 //2048
#define LOG2_DMA_MSG_SIZE_DIV_FLOAT_SIZE_PLUS1 15 //12 //11 //10 // log2(DMA_MSG_SIZE/4)+1
#define dma_msg_size_t uint16_t
typedef struct dma_msg_t
{
  uint8_t data[DMA_MSG_SIZE];
} dma_msg_t;
