// Compiler helper stuff
#pragma once

#define PRAGMA_MESSAGE(x) _Pragma(#x)

#define MAIN_MHZ(main_func, mhz)\
PRAGMA_MESSAGE(MAIN_MHZ main_func mhz)

#define MAIN_MHZ_GROUP(main_func, mhz, group)\
PRAGMA_MESSAGE(MAIN_MHZ main_func mhz group)
