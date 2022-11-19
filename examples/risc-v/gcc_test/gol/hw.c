// C code for various configured Game of Life accelerators
#include "hw_config.h"

// Hooks into hardware modules
#include "../../mem_map.h"

#ifdef COUNT_NEIGHBORS_IS_HW
#include "count_neighbors_hw/count_neighbors_hw.c"
#endif

#ifdef CELL_NEXT_STATE_IS_HW
#include "cell_next_state_hw/cell_next_state_hw.c"
#endif

#ifdef USE_NEXT_STATE_BUF_RW
#include "next_state_buf_rw/next_state_buf_rw.c"
#endif

#ifdef USE_MULTI_NEXT_STATE_BUF_RW
#include "multi_next_state_buf_rw/multi_next_state_buf_rw.c"
#endif

