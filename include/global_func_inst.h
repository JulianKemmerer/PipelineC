#pragma once
#include "compiler.h"
#include "fifo.h"

// Use global wires to connect up a new main func instance

#define global_func_inst_counter_t uint16_t

#define GLOBAL_FUNC_INST(inst_name, out_type, func_name, in_type) \
/* Global wires connected to instance */ \
in_type inst_name##_in; \
out_type inst_name##_out; \
MAIN(inst_name) \
void inst_name() \
{ \
  inst_name##_out = func_name(inst_name##_in); \
}


// NO IO regs version with id and valid
#define GLOBAL_FUNC_INST_W_VALID_ID(inst_name, out_type, func_name, in_type) \
typedef struct PPCAT(inst_name,_in_t){ \
  in_type data; \
  uint8_t id; \
  uint1_t valid; \
}PPCAT(inst_name,_in_t); \
typedef struct PPCAT(inst_name,_out_t){ \
  out_type data; \
  uint8_t id; \
  uint1_t valid; \
}PPCAT(inst_name,_out_t); \
/* Wrapper neeed to ensure globals behave as expected */\
PPCAT(inst_name,_out_t) PPCAT(inst_name,_wrapper)(in_type data, uint8_t id, uint1_t valid) \
{ \
  PPCAT(inst_name,_out_t) rv;\
  rv.data = func_name(data);\
  rv.id = id;\
  rv.valid = valid;\
  return rv;\
}\
/* Global wires connected to instance */ \
in_type inst_name##_in; \
uint8_t inst_name##_in_id; \
uint1_t inst_name##_in_valid; \
out_type inst_name##_out; \
uint8_t inst_name##_out_id; \
uint1_t inst_name##_out_valid; \
MAIN(inst_name) \
void inst_name() \
{ \
  PPCAT(inst_name,_out_t) wrapper_out = PPCAT(inst_name,_wrapper)(\
    inst_name##_in,\
    inst_name##_in_id,\
    inst_name##_in_valid\
  ); \
  inst_name##_out = wrapper_out.data; \
  inst_name##_out_id = wrapper_out.id; \
  inst_name##_out_valid = wrapper_out.valid;\
}


// Pipeline version includes IO regs for now...
#define GLOBAL_PIPELINE_INST(inst_name, out_type, func_name, in_type) \
in_type PPCAT(inst_name,_in_reg_func)(in_type i) \
{ \
  static in_type in_reg; \
  in_type rv = in_reg; \
  in_reg = i; \
  return rv; \
} \
out_type PPCAT(inst_name,_out_reg_func)(out_type o) \
{ \
  static out_type out_reg; \
  out_type rv = out_reg; \
  out_reg = o; \
  return rv; \
} \
 \
/* Global wires connected to instance */ \
in_type inst_name##_in; \
out_type inst_name##_out; \
MAIN(inst_name) \
void inst_name() \
{ \
  in_type i = PPCAT(inst_name,_in_reg_func)(inst_name##_in); \
  out_type o = func_name(i); \
  inst_name##_out = PPCAT(inst_name,_out_reg_func)(o); \
}


// Pipeline version with id and valid
#define GLOBAL_PIPELINE_INST_W_VALID_ID(inst_name, out_type, func_name, in_type) \
typedef struct PPCAT(inst_name,_in_reg_t){ \
  in_type data; \
  uint8_t id; \
  uint1_t valid; \
}PPCAT(inst_name,_in_reg_t); \
PRAGMA_MESSAGE(FUNC_WIRES PPCAT(inst_name,_in_reg_func))\
PPCAT(inst_name,_in_reg_t) PPCAT(inst_name,_in_reg_func)(in_type data, uint8_t id, uint1_t valid) \
{ \
  static PPCAT(inst_name,_in_reg_t) the_reg; \
  PPCAT(inst_name,_in_reg_t) rv = the_reg; \
  the_reg.data = data; \
  the_reg.id = id; \
  the_reg.valid = valid; \
  return rv; \
} \
typedef struct PPCAT(inst_name,_out_reg_t){ \
  out_type data; \
  uint8_t id; \
  uint1_t valid; \
}PPCAT(inst_name,_out_reg_t); \
PRAGMA_MESSAGE(FUNC_WIRES PPCAT(inst_name,_out_reg_func))\
PPCAT(inst_name,_out_reg_t) PPCAT(inst_name,_out_reg_func)(out_type data, uint8_t id, uint1_t valid) \
{ \
  static PPCAT(inst_name,_out_reg_t) the_reg; \
  PPCAT(inst_name,_out_reg_t) rv = the_reg; \
  the_reg.data = data; \
  the_reg.id = id; \
  the_reg.valid = valid; \
  return rv; \
} \
/* Global wires connected to instance */ \
in_type PPCAT(inst_name,_in); \
uint8_t PPCAT(inst_name,_in_id); \
uint1_t PPCAT(inst_name,_in_valid); \
out_type PPCAT(inst_name,_out); \
uint8_t PPCAT(inst_name,_out_id); \
uint1_t PPCAT(inst_name,_out_valid); \
MAIN(inst_name) \
void inst_name() \
{ \
  PPCAT(inst_name,_in_reg_t) i = PPCAT(inst_name,_in_reg_func)( \
    PPCAT(inst_name,_in), \
    PPCAT(inst_name,_in_id), \
    PPCAT(inst_name,_in_valid) \
  ); \
  out_type d = func_name(i.data); \
  PPCAT(inst_name,_out_reg_t) o = PPCAT(inst_name,_out_reg_func)( \
    d, \
    i.id,  \
    i.valid \
  ); \
  PPCAT(inst_name,_out) = o.data; \
  PPCAT(inst_name,_out_id) = o.id; \
  PPCAT(inst_name,_out_valid) = o.valid; \
}


#define GLOBAL_VALID_READY_PIPELINE_INST(inst_name, out_type, func_name, in_type, MAX_IN_FLIGHT)\
/* Inst name for underlying pipeline: PPCAT(inst_name,_no_handshake)*/\
GLOBAL_PIPELINE_INST_W_VALID_ID(PPCAT(inst_name,_no_handshake), out_type, func_name, in_type)\
/*Define FIFO to use for handshake PPCAT(inst_name,_FIFO)*/\
FIFO_FWFT(PPCAT(inst_name,_FIFO), out_type, MAX_IN_FLIGHT)\
/*Global wires for user*/\
stream(in_type) PPCAT(inst_name,_in); \
uint1_t PPCAT(inst_name,_in_ready); \
stream(out_type) PPCAT(inst_name,_out); \
uint1_t PPCAT(inst_name,_out_ready); \
/* main PPCAT(inst_name,_handshake) to wire up the handshake*/\
PRAGMA_MESSAGE(FUNC_WIRES PPCAT(inst_name,_handshake))\
MAIN(PPCAT(inst_name,_handshake))\
void PPCAT(inst_name,_handshake)(){\
  /* Keep count of how many words in FIFO*/\
  static global_func_inst_counter_t fifo_count;\
  /* Signal ready for input if room in fifo*/\
  PPCAT(inst_name,_in_ready) = (fifo_count < MAX_IN_FLIGHT);\
  /* Logic for input side of pipeline without handshake*/\
  /* Gate valid with ready signal*/\
  PPCAT(inst_name,_no_handshake_in_valid) = PPCAT(inst_name,_in.valid) & PPCAT(inst_name,_in_ready);\
  PPCAT(inst_name,_no_handshake_in) = PPCAT(inst_name,_in.data);\
  /* Free flow of data out of pipeline into fifo*/\
  uint1_t fifo_wr_en = PPCAT(inst_name,_no_handshake_out_valid);\
  out_type fifo_wr_data = PPCAT(inst_name,_no_handshake_out);\
  /* Dont need to check for not full/overflow since count used for ready*/\
  /* Read side of FIFO connected to top level outputs*/\
  uint1_t fifo_rd_en = PPCAT(inst_name,_out_ready);\
  /* The FIFO instance connected to outputs*/\
  PPCAT(inst_name,_FIFO_t) fifo_o = PPCAT(inst_name,_FIFO)(fifo_rd_en, fifo_wr_data, fifo_wr_en);\
  PPCAT(inst_name,_out.valid) = fifo_o.data_out_valid;\
  PPCAT(inst_name,_out.data) = fifo_o.data_out;\
  /* Count input writes and output reads from fifo*/\
  if(PPCAT(inst_name,_in.valid) & PPCAT(inst_name,_in_ready)){\
      fifo_count += 1;\
  }\
  if(PPCAT(inst_name,_out.valid) & PPCAT(inst_name,_out_ready)){\
      fifo_count -= 1;\
  }\
}


// Pipeline with id and valid that includes ONE HOT mux fan-in and fan-out
#define GLOBAL_PIPELINE_INST_W_ARB(inst_name, out_type, func_name, in_type, NUM_HOSTS) \
typedef struct PPCAT(inst_name,_in_reg_t){ \
  in_type datas[NUM_HOSTS]; \
  uint8_t ids[NUM_HOSTS]; \
  uint1_t valids[NUM_HOSTS]; \
}PPCAT(inst_name,_in_reg_t); \
PRAGMA_MESSAGE(FUNC_WIRES PPCAT(inst_name,_in_reg_func)) \
PPCAT(inst_name,_in_reg_t) PPCAT(inst_name,_in_reg_func)(in_type datas[NUM_HOSTS], uint8_t ids[NUM_HOSTS], uint1_t valids[NUM_HOSTS]) \
{ \
  static PPCAT(inst_name,_in_reg_t) the_reg; \
  PPCAT(inst_name,_in_reg_t) rv = the_reg; \
  the_reg.datas = datas; \
  the_reg.ids = ids; \
  the_reg.valids = valids; \
  return rv; \
} \
typedef struct PPCAT(inst_name,_out_reg_t){ \
  out_type datas[NUM_HOSTS]; \
  uint8_t ids[NUM_HOSTS]; \
  uint1_t valids[NUM_HOSTS]; \
}PPCAT(inst_name,_out_reg_t); \
PRAGMA_MESSAGE(FUNC_WIRES PPCAT(inst_name,_out_reg_func)) \
PPCAT(inst_name,_out_reg_t) PPCAT(inst_name,_out_reg_func)(out_type datas[NUM_HOSTS], uint8_t ids[NUM_HOSTS], uint1_t valids[NUM_HOSTS]) \
{ \
  static PPCAT(inst_name,_out_reg_t) the_reg; \
  PPCAT(inst_name,_out_reg_t) rv = the_reg; \
  the_reg.datas = datas; \
  the_reg.ids = ids; \
  the_reg.valids = valids; \
  return rv; \
} \
/* Global wires connected to instance */ \
in_type PPCAT(inst_name,_ins)[NUM_HOSTS]; \
uint8_t PPCAT(inst_name,_in_ids)[NUM_HOSTS]; \
uint1_t PPCAT(inst_name,_in_valids)[NUM_HOSTS]; \
out_type PPCAT(inst_name,_outs)[NUM_HOSTS]; \
uint8_t PPCAT(inst_name,_out_ids)[NUM_HOSTS]; \
uint1_t PPCAT(inst_name,_out_valids)[NUM_HOSTS]; \
MAIN(inst_name) \
PRAGMA_MESSAGE(FUNC_NO_ADD_IO_REGS inst_name) \
void inst_name() \
{ \
  /* IN REG*/ \
  PPCAT(inst_name,_in_reg_t) in_reg = PPCAT(inst_name,_in_reg_func)( \
    PPCAT(inst_name,_ins), \
    PPCAT(inst_name,_in_ids), \
    PPCAT(inst_name,_in_valids) \
  ); \
  /*IN MUX - TODO BINARY TREE*/ \
  in_type one_hot_selected_in_data; \
  uint32_t i; \
  for(i = 0; i < NUM_HOSTS; i+=1) \
  { \
    if(in_reg.valids[i]) \
    { \
      one_hot_selected_in_data = in_reg.datas[i]; \
    } \
  } \
  /*THE FUNC*/ \
  out_type data_out = func_name(one_hot_selected_in_data); \
  /*USE INPUT ONEHOT VALID FOR OUTPUT, EVERY OUT DATA IS SAME*/ \
  out_type data_outs[NUM_HOSTS]; \
  for(i = 0; i < NUM_HOSTS; i+=1) \
  { \
    data_outs[i] = data_out; \
  } \
  /* OUT REG */ \
  PPCAT(inst_name,_out_reg_t) o = PPCAT(inst_name,_out_reg_func)( \
    data_outs, \
    in_reg.ids,  \
    in_reg.valids \
  ); \
  PPCAT(inst_name,_outs) = o.datas; \
  PPCAT(inst_name,_out_ids) = o.ids; \
  PPCAT(inst_name,_out_valids) = o.valids; \
}


#define GLOBAL_PIPELINE_INST_W_ARB_NO_IO_REGS(inst_name, out_type, func_name, in_type, NUM_HOSTS) \
typedef struct PPCAT(inst_name,_in_t){ \
  in_type datas[NUM_HOSTS]; \
  uint8_t ids[NUM_HOSTS]; \
  uint1_t valids[NUM_HOSTS]; \
}PPCAT(inst_name,_in_t); \
typedef struct PPCAT(inst_name,_out_t){ \
  out_type datas[NUM_HOSTS]; \
  uint8_t ids[NUM_HOSTS]; \
  uint1_t valids[NUM_HOSTS]; \
}PPCAT(inst_name,_out_t); \
PPCAT(inst_name,_out_t) PPCAT(inst_name,_w_in_mux)(in_type datas[NUM_HOSTS], uint8_t ids[NUM_HOSTS], uint1_t valids[NUM_HOSTS]) \
{ \
  PPCAT(inst_name,_out_t) rv; \
  /*IN MUX - TODO BINARY TREE*/ \
  in_type one_hot_selected_in_data; \
  uint32_t i; \
  for(i = 0; i < NUM_HOSTS; i+=1) \
  { \
    if(valids[i]) \
    { \
      one_hot_selected_in_data = datas[i]; \
    } \
  } \
  /*THE FUNC*/ \
  out_type data_out = func_name(one_hot_selected_in_data); \
  /*USE INPUT ONEHOT VALID FOR OUTPUT, EVERY OUT DATA IS SAME*/ \
  out_type data_outs[NUM_HOSTS]; \
  for(i = 0; i < NUM_HOSTS; i+=1) \
  { \
    rv.datas[i] = data_out; \
  } \
  rv.ids = ids; \
  rv.valids = valids; \
  return rv; \
} \
/* Global wires connected to instance */ \
in_type PPCAT(inst_name,_ins)[NUM_HOSTS]; \
uint8_t PPCAT(inst_name,_in_ids)[NUM_HOSTS]; \
uint1_t PPCAT(inst_name,_in_valids)[NUM_HOSTS]; \
out_type PPCAT(inst_name,_outs)[NUM_HOSTS]; \
uint8_t PPCAT(inst_name,_out_ids)[NUM_HOSTS]; \
uint1_t PPCAT(inst_name,_out_valids)[NUM_HOSTS]; \
MAIN(inst_name) \
PRAGMA_MESSAGE(FUNC_NO_ADD_IO_REGS inst_name) \
void inst_name() \
{ \
  PPCAT(inst_name,_out_t) o = PPCAT(inst_name,_w_in_mux)( \
    PPCAT(inst_name,_ins), \
    PPCAT(inst_name,_in_ids), \
    PPCAT(inst_name,_in_valids) \
  ); \
  PPCAT(inst_name,_outs) = o.datas; \
  PPCAT(inst_name,_out_ids) = o.ids; \
  PPCAT(inst_name,_out_valids) = o.valids; \
}
