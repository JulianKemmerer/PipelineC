#include "compiler.h"

// TODO rename the DECL_OUTPUT's with some kind of #ifdef PMOD_O4_OUT etc

#ifdef PMOD_O4_WIRE
GLOBAL_OUT_WIRE_CONNECT(uint1_t, PMOD_O4_WIRE, PPCAT(PMOD_NAME,_o4))
#undef PMOD_O4_WIRE
#else
//DECL_OUTPUT(uint1_t, PPCAT(PMOD_NAME,_o4))
#endif

#ifdef PMOD_O3_WIRE
GLOBAL_OUT_WIRE_CONNECT(uint1_t, PMOD_O3_WIRE, PPCAT(PMOD_NAME,_o3))
#undef PMOD_O3_WIRE
#else
//DECL_OUTPUT(uint1_t, PPCAT(PMOD_NAME,_o3))
#endif

#ifdef PMOD_O2_WIRE
GLOBAL_OUT_WIRE_CONNECT(uint1_t, PMOD_O2_WIRE, PPCAT(PMOD_NAME,_o2))
#undef PMOD_O2_WIRE
#else
//DECL_OUTPUT(uint1_t, PPCAT(PMOD_NAME,_o2))
#endif

#ifdef PMOD_O1_WIRE
GLOBAL_OUT_WIRE_CONNECT(uint1_t, PMOD_O1_WIRE, PPCAT(PMOD_NAME,_o1))
#undef PMOD_O1_WIRE
#else
//DECL_OUTPUT(uint1_t, PPCAT(PMOD_NAME,_o1))
#endif

#undef PMOD_NAME



