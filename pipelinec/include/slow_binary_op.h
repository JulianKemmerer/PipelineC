#include "binary_tree.h"
#include "arrays.h"
#include "stream/stream.h"
#include "compiler.h"

#define DECL_SLOW_BINARY_OP(\
  name, II,\
  out_t, OP, left_t, right_t, N_INPUTS)\
typedef struct PPCAT(name,_input_ser_t){\
  left_t l[CEIL_DIV(N_INPUTS,II)];\
  right_t r[CEIL_DIV(N_INPUTS,II)];\
  uint1_t valid;\
}PPCAT(name,_input_ser_t);\
PPCAT(name,_input_ser_t) PPCAT(name,_input_ser)(left_t l[N_INPUTS], right_t r[N_INPUTS], uint1_t in_valid)\
{\
  /* If active */\
  static uint1_t valid;\
  /* Count of iters */\
  static uint16_t counter;\
  /* Data for each iter*/\
  static left_t l_datas[II][CEIL_DIV(N_INPUTS,II)];\
  static right_t r_datas[II][CEIL_DIV(N_INPUTS,II)];\
\
  /* Reg input data*/\
  if(in_valid){\
    /* Reset counter*/\
    valid = 1;\
    counter = 0;\
    /* Split into chunks based on II*/\
    uint32_t i = 0;\
    uint32_t cycle_i;\
    uint32_t per_cycle_i;\
    for (cycle_i = 0; cycle_i < II; cycle_i+=1)\
    {\
      for (per_cycle_i = 0; per_cycle_i < CEIL_DIV(N_INPUTS,II); per_cycle_i+=1)\
      {\
        if(i<N_INPUTS){\
          l_datas[cycle_i][per_cycle_i] = l[i];\
          r_datas[cycle_i][per_cycle_i] = r[i];\
        }else{\
          l_datas[cycle_i][per_cycle_i] = 0;\
          r_datas[cycle_i][per_cycle_i] = 0;\
        }\
        i += 1;\
      }\
    } \
  }\
  /* Outputs*/\
  PPCAT(name,_input_ser_t) rv;\
  rv.l = l_datas[0];\
  rv.r = r_datas[0];\
  rv.valid = valid;\
  uint1_t last_iter = counter==(II-1);\
\
  /* Next*/\
  counter += 1;\
  /* Shift for next iter data*/\
  ARRAY_SHIFT_DOWN(l_datas, II, 1)\
  ARRAY_SHIFT_DOWN(r_datas, II, 1)\
  \
  /* Reset at last iter*/\
  if(last_iter){\
    valid = 0;\
    counter = 0;\
  }\
  \
  return rv;\
}\
\
/* Buffer iter outputs*/\
typedef struct PPCAT(name,_out_t){\
  out_t data[N_INPUTS];\
  uint1_t valid;\
}PPCAT(name,_out_t);\
PPCAT(name,_out_t) PPCAT(name,_out_deser)(out_t partial_outs[CEIL_DIV(N_INPUTS,II)], uint1_t shifter_out_valid)\
{\
  static out_t buff[(II)*CEIL_DIV(N_INPUTS,II)];\
  static uint16_t counter;\
  static uint1_t valid;\
  PPCAT(name,_out_t) rv;\
  if(shifter_out_valid){\
    ARRAY_SHIFT_INTO_TOP(buff, (II)*CEIL_DIV(N_INPUTS,II), partial_outs, CEIL_DIV(N_INPUTS,II))\
    rv.valid = counter==(II-1);\
    counter += 1;\
  }\
  uint32_t i;\
  for(i = 0; i < N_INPUTS; i+=1)\
  {\
    rv.data[i] = buff[i];\
  }\
  if(rv.valid){\
    counter = 0;\
  }\
  return rv;\
}\
\
/* The slow II=N binary op*/\
/* Break into N_INPUTS/II sized chunks */\
PPCAT(name,_out_t) name(left_t l[N_INPUTS], right_t r[N_INPUTS], uint1_t valid)\
{\
  /* Register input entire data, shift out chunks at a time*/\
  /* One valid in produces produces stream of N=II valids out*/\
  PPCAT(name,_input_ser_t) serializer = PPCAT(name,_input_ser)(l, r, valid);\
\
  /* N/II ops in parallel*/ \
  out_t partial_outs[CEIL_DIV(N_INPUTS,II)];\
  uint32_t i;\
  for(i = 0; i < CEIL_DIV(N_INPUTS,II); i+=1)\
  {\
    partial_outs[i] = serializer.l[i] OP serializer.r[i];\
  }\
\
  /* Buffer iters outputs*/\
  /* Produces one slow stream of N input elements */\
  PPCAT(name,_out_t) deserializer = PPCAT(name,_out_deser)(partial_outs, serializer.valid);\
\
  return deserializer;\
}

