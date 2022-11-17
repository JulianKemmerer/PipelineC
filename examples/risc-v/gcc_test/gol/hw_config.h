#pragma once

// Configure various hardware acceleration

// Enable or disable frame buffer
#define FRAME_BUFFER
#define FRAME_BUFFER_LATENCY 1 // 1=BRAM,0=LUTRAM
//#define FRAME_BUFFER_EXTRA_PORTS_HAVE_IO_REGS

// Counting live neighbor cells
#define COUNT_NEIGHBORS_IS_HW
//#define COUNT_NEIGHBORS_IS_MEM_MAPPED

// Determining cell next state
#define CELL_NEXT_STATE_IS_HW
//#define CELL_NEXT_STATE_IS_MEM_MAPPED

// Combo computing next state and read+writing buffers
#define USE_NEXT_STATE_BUF_RW
#define NEXT_STATE_BUF_RW_IS_HW
#define NEXT_STATE_BUF_RW_IS_MEM_MAPPED

// Derive and include whats enabled

#ifdef FRAME_BUFFER
#ifdef NEXT_STATE_BUF_RW_IS_HW
#define FRAME_BUFFER_NUM_EXTRA_PORTS 1
#define FRAME_BUFFER_DISABLE_CPU_PORT
#define LINE_BUFS_NUM_EXTRA_PORTS 1
#elif defined(CELL_NEXT_STATE_IS_HW)
#define FRAME_BUFFER_NUM_EXTRA_PORTS 1
#define FRAME_BUFFER_PORT2_RD_ONLY
#elif defined(COUNT_NEIGHBORS_IS_HW)
#define FRAME_BUFFER_NUM_EXTRA_PORTS 1
#define FRAME_BUFFER_PORT2_RD_ONLY
#endif
#ifdef FRAME_BUFFER_DISABLE_CPU_PORT
#if FRAME_BUFFER_LATENCY == 1
#define FRAME_BUFFER_EXTRA_PORT0_RW
#endif
#endif
#include "../../frame_buffer.h"
#endif

#ifdef CELL_NEXT_STATE_IS_HW
#ifdef CELL_NEXT_STATE_IS_MEM_MAPPED
#include "cell_next_state_hw/mem_map.h"
#endif
#include "cell_next_state_hw/cell_next_state_hw.h"
#endif

#ifdef COUNT_NEIGHBORS_IS_HW
#ifdef COUNT_NEIGHBORS_IS_MEM_MAPPED
#include "count_neighbors_hw/mem_map.h"
#endif
#include "count_neighbors_hw/count_neighbors_hw.h"
#endif
