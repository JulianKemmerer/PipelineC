#include "uintN_t.h"
#include "axi/axis.h"
#include "debug_port.h"

DECL_OUTPUT(uint32_t, out_data)
DECL_OUTPUT(uint1_t, out_valid)
DECL_OUTPUT(uint1_t, in_ready)

#pragma MAIN pipelineC_ip
#pragma MAIN_MHZ pipelineC_ip 300.0
#pragma PART "xcu50-fsvh2104-2-e"

void pipelineC_ip (
    uint32_t in_data,
    uint1_t in_valid,
    uint1_t out_ready
) {
    if (in_valid & out_ready) {
        out_data = in_data + 1;
        out_valid = 1;
        in_ready = 1;
    } else {
        out_data = 0;
        out_valid = 0;
        in_ready = 0;
    }
}
