#pragma PART "xc7a100tcsg324-1"

#include "uintN_t.h"
#include "stream/stream.h"
DECL_STREAM_TYPE(uint32_t)

// TODO move all module board and io to here via includes

// CPU CLK MHZ const
#include "../../clock/software/clock.h"

// Board config:
// DVP board config
#include "../../dvp/hardware/board_config.h"
// I2S (unused since over ETH now)
//#include "../../i2s/hardware/board_config.h"
// VGA
#include "../../vga/hardware/board_config.h"

// The Arty base board config
#include "board/arty.h"

// Top level IO connections for configured board
//#include "i2s/i2s_regs.c"
#include "../../vga/hardware/io.c"
#include "../../dvp/hardware/io.c"
