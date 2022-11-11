// C code for various configured Game of Life accelerators
#include "hw_config.h"

// Hooks into hardware buffers, ex. frame_buf_write, count_live_neighbour_cells_hw
#include "../../mem_map.h"

#ifdef FRAME_BUFFER
#ifdef __PIPELINEC__ // Only HW stuff in .c file
#include "../../frame_buffer.c"
#endif
#endif

#ifdef COUNT_NEIGHBORS_IS_HW
#include "count_neighbors_hw/count_neighbors_hw.c"
#endif

#ifdef CELL_NEXT_STATE_IS_HW
#include "cell_next_state_hw/cell_next_state_hw.c"
#endif