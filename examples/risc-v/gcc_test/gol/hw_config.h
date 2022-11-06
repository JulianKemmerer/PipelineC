#pragma once

// Configure various hardware acceleration

// Enable or disable frame buffer
#define FRAME_BUFFER

// Counting live neighbor cells
//#define COUNT_NEIGHBORS_IS_HW

// Include whats enabled

#ifdef FRAME_BUFFER
#include "../../frame_buffer.h"
#endif

#ifdef COUNT_NEIGHBORS_IS_HW
#include "count_neighbors_hw/count_neighbors_hw.h"
#endif