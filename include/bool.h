#pragma once

#ifndef __PIPELINEC__
#include <stdbool.h>
#ifndef __cplusplus
#define uint1_t bool
#endif

#else // __PIPELINEC__

// Temp work around for typedef of bool 
// https://github.com/JulianKemmerer/PipelineC/issues/52
#define bool uint1_t
#define true 1
#define false 0

#endif