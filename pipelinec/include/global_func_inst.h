#pragma once
#include "compiler.h"

// Use global wires to connect up a new main func instance

#define GLOBAL_FUNC_INST(inst_name, out_type, func_name, in_type) \
/* Global wires connected to instance */ \
in_type inst_name##_in; \
out_type inst_name##_out; \
MAIN(inst_name) \
void inst_name() \
{ \
  inst_name##_out = func_name(inst_name##_in); \
}

// Pipeline version includes IO regs for now...
#define GLOBAL_PIPELINE_INST(inst_name, out_type, func_name, in_type) \
in_type inst_name##_in_reg_func(in_type i) \
{ \
  static in_type in_reg; \
  in_type rv = in_reg; \
  in_reg = i; \
  return rv; \
} \
out_type inst_name##_out_reg_func(out_type o) \
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
  in_type i = inst_name##_in_reg_func(inst_name##_in); \
  out_type o = func_name(i); \
  inst_name##_out = inst_name##_out_reg_func(o); \
}
