#pragma once

// Configure various hardware acceleration

// Enable or disable frame buffer
#define FRAME_BUFFER
#define FRAME_BUFFER_LATENCY 1 // 1=BRAM,0=LUTRAM
//#define FRAME_BUFFER_EXTRA_PORTS_HAVE_IO_REGS

// Counting live neighbor cells
//#define COUNT_NEIGHBORS_IS_HW

// Include whats enabled

#ifdef FRAME_BUFFER
#ifdef COUNT_NEIGHBORS_IS_HW
#define FRAME_BUFFER_NUM_EXTRA_PORTS 1
#define FRAME_BUFFER_PORT2_RD_ONLY
#endif
#include "../../frame_buffer.h"
#endif

#ifdef COUNT_NEIGHBORS_IS_HW
#include "count_neighbors_hw/count_neighbors_hw.h"
#endif