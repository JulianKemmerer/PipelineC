#pragma once
#include "compiler.h"
#include "uintN_t.h"
#include "stream/stream.h"

#define hs_in(type_t) PPCAT(type_t,_handshake_inputs_t)
#define hs_out(type_t) PPCAT(type_t,_handshake_outputs_t)

#define DECL_HANDSHAKE_TYPE(type_t)\
typedef struct hs_in(type_t)\
{\
  stream(type_t) stream_in;\
  uint1_t ready_for_stream_out;\
}hs_in(type_t);\
typedef struct hs_out(type_t)\
{\
  stream(type_t) stream_out;\
  uint1_t ready_for_stream_in;\
}hs_out(type_t); \
/* DONT LET USERS SEE/USE _handshake_t since (make weird name?)*/\
/* not make sense unless know opposite dir ready stuff?*/\
/* only used with macros that know?*/\
typedef struct PPCAT(HANDSHAKE_t_,type_t)\
{\
  stream(type_t) stream;\
  uint1_t ready;\
}PPCAT(HANDSHAKE_t_,type_t);\

#define DECL_HANDSHAKE_INST_TYPE(out_type_t, in_type_t)\
typedef struct PPCAT(HANDSHAKE_IO_t_,PPCAT(out_type_t,in_type_t)){\
  PPCAT(HANDSHAKE_t_,in_type_t) in_handshake;\
  PPCAT(HANDSHAKE_t_,out_type_t) out_handshake;\
}PPCAT(HANDSHAKE_IO_t_,PPCAT(out_type_t,in_type_t));

#define HANDSHAKE_FROM_STREAM(hs_inst_name, input_stream, ready_for_input_stream)\
hs_inst_name.in_handshake.stream = input_stream;\
ready_for_input_stream = hs_inst_name.in_handshake.ready;

#define HANDSHAKE_CONNECT(lhs_inst, rhs_inst)\
lhs_inst.in_handshake.stream = rhs_inst.out_handshake.stream;\
rhs_inst.out_handshake.ready = lhs_inst.in_handshake.ready;

#define STREAM_FROM_HANDSHAKE(output_stream, ready_for_output_stream, hs_inst_name)\
output_stream = hs_inst_name.out_handshake.stream;\
hs_inst_name.out_handshake.ready = ready_for_output_stream;

// Connect input and output streams/HS to INST
// ONLY FOR ONE HS IN ONE HS OUT
// not for join split etc
// CANNOT AUTO NULL FEEDBACK SINCE MIXED DIRECTION!
// WILL IT WORK TO MIX partially driven feedback/structs etc?
// if doesnt work then in_hs/_inputs_t types need to be feedback
// and driven at end of process...
#define DECL_HANDSHAKE_INST(name, out_type, func_name, in_type)\
PPCAT(HANDSHAKE_IO_t_,PPCAT(out_type,in_type)) name;\
FEEDBACK(name)\
hs_in(in_type) PPCAT(INST_INPUT_,name);\
PPCAT(INST_INPUT_,name).stream_in = name.in_handshake.stream;\
PPCAT(INST_INPUT_,name).ready_for_stream_out = name.out_handshake.ready;\
hs_out(out_type) PPCAT(INST_OUTPUT_,name) = func_name(PPCAT(INST_INPUT_,name));\
name.out_handshake.stream = PPCAT(INST_OUTPUT_,name).stream_out;\
name.in_handshake.ready = PPCAT(INST_OUTPUT_,name).ready_for_stream_in;
