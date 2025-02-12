// Compiler helper stuff
#pragma once

/*
 * Concatenate preprocessor tokens A and B without expanding macro definitions
 * (however, if invoked from a macro, macro arguments are expanded).
 */
#define PPCAT_NX(A, B) A ## B

/*
 * Concatenate preprocessor tokens A and B after macro-expanding them.
 */
#define PPCAT(A, B) PPCAT_NX(A, B)

// Bool stuff
#include "bool.h"

// Mathy stuff
#define ROUND0UP1(x)\
((x)==0 ? 1 : x)

#define CLOG2(N)\
(\
(N)<=1 ? 0 :\
(N)<=2 ? 1 :\
(N)<=4 ? 2 :\
(N)<=8 ? 3 :\
(N)<=16 ? 4 :\
(N)<=32 ? 5 :\
(N)<=64 ? 6 :\
(N)<=128 ? 7 :\
(N)<=256 ? 8 :\
-1)
/*(N)<=512 ? 9 :\
(N)<=1024 ? 10 :\
(N)<=2048 ? 11 :\
(N)<=4096 ? 12 :\
(N)<=8192 ? 13 :\
(N)<=16384 ? 14 :\
(N)<=32768 ? 15 :\
(N)<=65536 ? 16 :\*/

#define INT_CAST_ROUNDS_DOWN(f)\
( ((f)-(float)(int64_t)(f)) > 0.0 )

#define CEIL(f)\
( INT_CAST_ROUNDS_DOWN(f) ? (int64_t)(f) + 1 : (int64_t)(f) )

#define FLOOR(f)\
( INT_CAST_ROUNDS_DOWN(f) ? (int64_t)(f) : (int64_t)(f) - 1 )

#define CEIL_DIV(N,D)\
CEIL((float)(N)/(float)(D))

#define FLOOR_DIV(N,D)\
FLOOR((float)(N)/(float)(D))

// Can't parse attributes
// https://github.com/eliben/pycparser/wiki/FAQ#what-do-i-do-about-__attribute__
#ifdef __PIPELINEC__
#define __attribute__(x)
#endif

// Pragma helpers
#define PRAGMA_MESSAGE_(x) _Pragma(#x)
#define PRAGMA_MESSAGE(x) PRAGMA_MESSAGE_(x)

#define CLK_MHZ(clock, mhz)\
PRAGMA_MESSAGE(CLK_MHZ clock mhz)

#define CLK_MHZ_GROUP(clock, mhz, group)\
PRAGMA_MESSAGE(CLK_MHZ_GROUP clock mhz group)

#define MAIN(main_func)\
PRAGMA_MESSAGE(MAIN main_func)

#define MAIN_MHZ(main_func, mhz)\
PRAGMA_MESSAGE(MAIN_MHZ main_func mhz)

#define MAIN_SYN_MHZ(main_func, mhz)\
PRAGMA_MESSAGE(MAIN_SYN_MHZ main_func mhz)

#define MAIN_MHZ_GROUP(main_func, mhz, group)\
PRAGMA_MESSAGE(MAIN_MHZ main_func mhz group)

#define BUILT_IN_RAM_FUNC_LATENCY(call_location_func_name, ram_name, latency) \
PRAGMA_MESSAGE(FUNC_LATENCY PPCAT(PPCAT(call_location_func_name,_),ram_name) latency)

#define FEEDBACK(wire)\
PRAGMA_MESSAGE(FEEDBACK wire)

#define DECL_FEEDBACK_WIRE(type_t, name)\
type_t name;\
PRAGMA_MESSAGE(FEEDBACK name)

// Work around for user top level IO:
// https://github.com/JulianKemmerer/PipelineC/issues/123
// https://github.com/JulianKemmerer/PipelineC/issues/130
#define DECL_INPUT(type_t, name) \
type_t name; \
PRAGMA_MESSAGE(MAIN name) \
PRAGMA_MESSAGE(FUNC_WIRES name) \
void name(type_t val_input) \
{ \
  name = val_input;\
}
#define DECL_INPUT_REG(type_t, name) \
type_t name; \
PRAGMA_MESSAGE(MAIN name) \
PRAGMA_MESSAGE(FUNC_WIRES name) \
void name(type_t val_input) \
{ \
  static type_t the_reg; \
  name = the_reg; \
  the_reg = val_input;\
}
#define DECL_OUTPUT(type_t, name) \
type_t name; \
PRAGMA_MESSAGE(MAIN name) \
PRAGMA_MESSAGE(FUNC_WIRES name) \
type_t name() \
{ \
  return name; \
}
#define DECL_OUTPUT_REG(type_t, name) \
type_t name; \
PRAGMA_MESSAGE(MAIN name) \
PRAGMA_MESSAGE(FUNC_WIRES name) \
type_t name() \
{ \
  static type_t the_reg; \
  type_t rv = the_reg; \
  the_reg = name; \
  return rv; \
}
#define GLOBAL_OUT_WIRE_CONNECT(type_t, wire, name)\
type_t name; \
PRAGMA_MESSAGE(MAIN PPCAT(name,_connect)) \
PRAGMA_MESSAGE(FUNC_WIRES PPCAT(name,_connect)) \
void PPCAT(name,_connect)(){ \
  wire = name; \
}
#define GLOBAL_OUT_REG_WIRE_CONNECT(type_t, wire, name)\
type_t name; \
PRAGMA_MESSAGE(MAIN PPCAT(name,_connect)) \
PRAGMA_MESSAGE(FUNC_WIRES PPCAT(name,_connect)) \
void PPCAT(name,_connect)(){ \
  static type_t the_reg; \
  wire = the_reg; \
  the_reg = name; \
}
#define GLOBAL_IN_WIRE_CONNECT(type_t, name, wire)\
type_t name; \
PRAGMA_MESSAGE(MAIN PPCAT(name,_connect)) \
PRAGMA_MESSAGE(FUNC_WIRES PPCAT(name,_connect)) \
void PPCAT(name,_connect)(){ \
  name = wire; \
}
#define GLOBAL_IN_REG_WIRE_CONNECT(type_t, name, wire)\
type_t name; \
PRAGMA_MESSAGE(MAIN PPCAT(name,_connect)) \
PRAGMA_MESSAGE(FUNC_WIRES PPCAT(name,_connect)) \
void PPCAT(name,_connect)(){ \
  static type_t the_reg; \
  name = the_reg; \
  the_reg = wire; \
}


// Split a main funciton instance into N globally available function calls
// Maybe code gen some day?
#define MAIN_SPLIT2( \
  main_split_out_t, \
  main_name, \
  part_0_name, \
  part_0_name_in_t, \
  part_0_name_out_t, \
  part_1_name, \
  part_1_name_in_t, \
  part_1_name_out_t \
) \
/* 'ports' of global wires, can't be single array*/ \
part_0_name_in_t main_name##_##part_0_name##_in; \
part_0_name_out_t main_name##_##part_0_name##_out; \
part_1_name_in_t main_name##_##part_1_name##_in; \
part_1_name_out_t main_name##_##part_1_name##_out; \
/* One helper func per port */ \
part_0_name_out_t part_0_name(part_0_name_in_t inputs){ \
  main_name##_##part_0_name##_in = inputs; \
  return main_name##_##part_0_name##_out; \
} \
part_1_name_out_t part_1_name(part_1_name_in_t inputs){ \
  main_name##_##part_1_name##_in = inputs; \
  return main_name##_##part_1_name##_out; \
} \
/* And the actual main instance of the user's main func*/ \
MAIN(main_name##_SPLIT2) \
void main_name##_SPLIT2() \
{ \
  main_split_out_t main_out = main_name( \
    main_name##_##part_0_name##_in, \
    main_name##_##part_1_name##_in \
  );\
  main_name##_##part_0_name##_out = main_out.part_0_name; \
  main_name##_##part_1_name##_out = main_out.part_1_name; \
}
#define MAIN_SPLIT3( \
  main_split_out_t, \
  main_name, \
  part_0_name, \
  part_0_name_in_t, \
  part_0_name_out_t, \
  part_1_name, \
  part_1_name_in_t, \
  part_1_name_out_t, \
  part_2_name, \
  part_2_name_in_t, \
  part_2_name_out_t \
) \
/* 'ports' of global wires, can't be single array*/ \
part_0_name_in_t main_name##_##part_0_name##_in; \
part_0_name_out_t main_name##_##part_0_name##_out; \
part_1_name_in_t main_name##_##part_1_name##_in; \
part_1_name_out_t main_name##_##part_1_name##_out; \
part_2_name_in_t main_name##_##part_2_name##_in; \
part_2_name_out_t main_name##_##part_2_name##_out; \
/* One helper func per port */ \
part_0_name_out_t part_0_name(part_0_name_in_t inputs){ \
  main_name##_##part_0_name##_in = inputs; \
  return main_name##_##part_0_name##_out; \
} \
part_1_name_out_t part_1_name(part_1_name_in_t inputs){ \
  main_name##_##part_1_name##_in = inputs; \
  return main_name##_##part_1_name##_out; \
} \
part_2_name_out_t part_2_name(part_2_name_in_t inputs){ \
  main_name##_##part_2_name##_in = inputs; \
  return main_name##_##part_2_name##_out; \
} \
/* And the actual main instance of the user's main func*/ \
MAIN(main_name##_SPLIT3) \
void main_name##_SPLIT3() \
{ \
  main_split_out_t main_out = main_name( \
    main_name##_##part_0_name##_in, \
    main_name##_##part_1_name##_in, \
    main_name##_##part_2_name##_in \
  );\
  main_name##_##part_0_name##_out = main_out.part_0_name; \
  main_name##_##part_1_name##_out = main_out.part_1_name; \
  main_name##_##part_2_name##_out = main_out.part_2_name; \
}
