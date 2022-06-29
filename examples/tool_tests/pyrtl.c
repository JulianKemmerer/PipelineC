// Relies on OPEN_TOOLS ghdl->yosys flow first...
// Do not specify #pragma PART
// TODO support for specifying ASIC tech nanometers
#pragma MAIN_MHZ my_pipeline 250.0
#include "examples/pipeline.c"