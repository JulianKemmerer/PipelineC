// Board top level config

// Devices can configure board top level
// DVP board config
#include "../../dvp/hardware/board_config.h"
// I2S (unused since over ETH now)
//#include "../../i2s/hardware/board_config.h"
// VGA
#include "../../vga/hardware/board_config.h"

// The Arty base board config
#pragma PART "xc7a100tcsg324-1" // TODO move into arty.h?
#include "board/arty.h"
