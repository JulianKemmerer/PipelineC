// Compiler helper stuff
#pragma once

#define PRAGMA_MESSAGE(x) _Pragma(#x)

#define MAIN(main_func)\
PRAGMA_MESSAGE(MAIN main_func)

#define MAIN_MHZ(main_func, mhz)\
PRAGMA_MESSAGE(MAIN_MHZ main_func mhz)

#define MAIN_SYN_MHZ(main_func, mhz)\
PRAGMA_MESSAGE(MAIN_SYN_MHZ main_func mhz)

#define MAIN_MHZ_GROUP(main_func, mhz, group)\
PRAGMA_MESSAGE(MAIN_MHZ main_func mhz group)

#define CLK_MHZ(clock, mhz)\
PRAGMA_MESSAGE(CLK_MHZ clock mhz)

// Temp work around for C++/bool types, see github issue
// https://github.com/JulianKemmerer/PipelineC/issues/24
#ifdef __PIPELINEC__
#define bool uint1_t
#define true 1
#define false 0
#define and &
#else
#ifndef __cplusplus
#define and &&
#define uint1_t bool
#endif
#endif
