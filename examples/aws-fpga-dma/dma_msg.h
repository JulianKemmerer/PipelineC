// Code wrapping the AXI4 (FPGA) and
// file (XDMA driver) abstractions to a common 'DMA message'

#pragma once
#include "../../uintN_t.h"

#define DMA_MSG_SIZE 256 //32768
// Current DMA example requires 64 byte aligned+continuous messages
#define dma_msg_size_t uint16_t
typedef struct dma_msg_t
{
  uint8_t data[DMA_MSG_SIZE];
} dma_msg_t;
// Stream version for buffering
typedef struct dma_msg_s
{
  dma_msg_t data;
  uint1_t valid;
} dma_msg_s;
