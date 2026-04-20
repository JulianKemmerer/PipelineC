// Board top level config

// Get constant from header written by make flow
#include "../../../pipelinec_makefile_config.h"

// Devices can configure board top level
//#include "device/board_config.h"

#pragma PART "ICE40UP5K-SG48" // TODO move into board file?
// Board specific config
#ifdef BOARD_PICO
#include "board/pico_ice.h"
#elif defined(BOARD_PICO2)
#include "board/pico2_ice.h"
#else
#warning "Unknown board?"
#endif
