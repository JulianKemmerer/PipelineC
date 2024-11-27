#include "binary_tree.h"
#include "arrays.h"
#include "stream/stream.h"
#include "compiler.h"

#define DECL_SLOW_BINARY_TREE(\
  name, II, ii_div2_slow_ii_tree, /* II/2 slow binary tree of II elements*/\
  out_t, tree_t, in_t, OP, N_INPUTS)\
typedef struct PPCAT(name,_input_ser_t){\
  in_t single_iter_data[CEIL_DIV(N_INPUTS,II)];\
  uint1_t valid;\
}PPCAT(name,_input_ser_t);\
PPCAT(name,_input_ser_t) PPCAT(name,_input_ser)(in_t in_data[N_INPUTS], uint1_t in_valid)\
{\
  /* If active */\
  static uint1_t valid;\
  /* Count of iters */\
  static uint16_t counter;\
  /* Data for each iter*/\
  static in_t iter_datas[II][CEIL_DIV(N_INPUTS,II)];\
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
          iter_datas[cycle_i][per_cycle_i] = in_data[i];\
        }else{\
          iter_datas[cycle_i][per_cycle_i] = 0;\
        }\
        i += 1;\
      }\
    } \
  }\
  /* Outputs*/\
  PPCAT(name,_input_ser_t) rv;\
  rv.single_iter_data = iter_datas[0];\
  rv.valid = valid;\
  uint1_t last_iter = counter==(II-1);\
\
  /* Next*/\
  counter += 1;\
  /* Shift for next iter data*/\
  ARRAY_SHIFT_DOWN(iter_datas, II, 1)\
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
/* Declare component smaller trees*/\
/* Can only declare the not slow tree inside this macro since recursion is hard*/\
/* Not slow II=1 pipeline of fewer HW OPS*/\
DECL_BINARY_OP_TREE(\
  PPCAT(name,_partial_bin_op_tree_func),\
  tree_t, tree_t, in_t, OP, CEIL_DIV(N_INPUTS,II), CLOG2(CEIL_DIV(N_INPUTS,II))\
)\
\
/* Buffer iters outputs*/\
/* Produces one slow II=n-iters stream of n iters elements */\
typedef struct PPCAT(name,_out_deser_t){\
  tree_t data[II];\
  uint1_t valid;\
}PPCAT(name,_out_deser_t);\
PPCAT(name,_out_deser_t) PPCAT(name,_out_deser)(tree_t partial_out, uint1_t shifter_out_valid)\
{\
  static tree_t buff[II];\
  static uint16_t counter;\
  static uint1_t valid;\
  PPCAT(name,_out_deser_t) rv;\
  if(shifter_out_valid){\
    ARRAY_1SHIFT_INTO_BOTTOM(buff, II, partial_out)\
    rv.valid = counter==(II-1);\
    counter += 1;\
  }\
  rv.data = buff;\
  if(rv.valid){\
    counter = 0;\
  }\
  return rv;\
}\
\
/* The slow II=N binary tree*/\
/* Break into N_INPUTS/II sized chunks */\
/* and then one final slow binary tree for those */\
stream(out_t) name(in_t in_data[N_INPUTS], uint1_t valid)\
{\
  /* Sanity check params?*/\
  if(II==1){\
    do_not_use_slow_funcs_with_II_of_1();\
  }\
  \
  /* Register input entire data, shift out chunks at a time*/\
  /* One valid in produces produces stream of N=II valids out*/\
  PPCAT(name,_input_ser_t) serializer = PPCAT(name,_input_ser)(in_data, valid);\
\
  /* Iteration pieces through normal II=1 pipeline*/\
  tree_t single_iter_data_out = PPCAT(name,_partial_bin_op_tree_func)(serializer.single_iter_data);\
\
  /* Buffer iters outputs*/\
  /* Produces one slow II=N stream of N iters elements */\
  PPCAT(name,_out_deser_t) deserializer = PPCAT(name,_out_deser)(single_iter_data_out, serializer.valid);\
\
  /* Finaly slow binary op tree for the slow II=N of N elements pipeline*/\
  stream(out_t) out = ii_div2_slow_ii_tree(deserializer.data, deserializer.valid);\
\
  return out;\
}

