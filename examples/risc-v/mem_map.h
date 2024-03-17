#pragma once

// Helpers for building memory maps
// TODO move into risc-v.h?

// Base/default version without user types
typedef struct mem_map_out_t
{
  uint1_t addr_is_mapped;
  uint32_t rd_data;
}mem_map_out_t;

// Base struct builder helper with user types
#define riscv_mem_map_mod_out_t(mem_map_outputs_t)\
PPCAT(mem_map_outputs_t,_riscv_mem_map_mod_out_t)

#define DECL_MEM_MAP_MOD_OUT_T(mem_map_outputs_t)\
typedef struct riscv_mem_map_mod_out_t(mem_map_outputs_t)\
{\
  uint1_t addr_is_mapped;\
  uint32_t rd_data;\
  mem_map_outputs_t outputs;\
}riscv_mem_map_mod_out_t(mem_map_outputs_t);

#define RISCV_MEM_MAP_MOD_INPUTS(mem_map_inputs_t)\
uint32_t addr, uint32_t wr_data, uint1_t wr_byte_ens[4],\
mem_map_inputs_t inputs


// Helper macros to reduce code in and around mem_map_module
//  TODO: Make read-write struct byte array muxing simpler, not all alignments handled are possible.

// Assign a word variable to the memory map
#define WORD_MM_ENTRY(ADDR, var)\
else if(addr==ADDR){\
  o.addr_is_mapped = 1;\
  o.rd_data = var;\
  if(wr_byte_ens[0]){\
    var = wr_data;\
  }\
}

// Assign a struct variable to the memory map
#define STRUCT_MM_ENTRY(ADDR, type_t, var)\
else if( (addr>=ADDR) & (addr<(ADDR+sizeof(type_t))) ){\
  o.addr_is_mapped = 1;\
  /* Convert to bytes*/\
  type_t##_bytes_t var##_bytes = type_t##_to_bytes(var);\
  uint32_t var##_bytes_offset = addr - ADDR;\
  /* Assemble rd data bytes*/\
  uint32_t var##_byte_i;\
  uint8_t var##_rd_bytes[4];\
  for(var##_byte_i=0;var##_byte_i<4;var##_byte_i+=1){\
    var##_rd_bytes[var##_byte_i] = var##_bytes.data[var##_bytes_offset+var##_byte_i];\
  }\
  o.rd_data = uint8_array4_le(var##_rd_bytes);\
  /* Drive write bytes*/\
  for(var##_byte_i=0;var##_byte_i<4;var##_byte_i+=1){\
    if(wr_byte_ens[var##_byte_i]){\
      var##_bytes.data[var##_bytes_offset+var##_byte_i] = wr_data >> (var##_byte_i*8);\
    }\
  }\
  /* Convert back to type*/\
  var = bytes_to_##type_t(var##_bytes);\
}

// Assign input register word to mem map
#define IN_REG_WORD_MM_ENTRY(ADDR, name, field)\
WORD_MM_ENTRY(ADDR, name##_in_reg.field)

// Connect outputs to registers for better fmax
#define OUT_REG(name)\
name##_out_reg = name##_out;

// Define IO regs and connect inputs with single cycle .valid field
#define VALID_PULSE_IO_REGS_DECL(name, out_t, in_t)\
/*In+out registers for wires, for better fmax*/\
static in_t name##_in_reg;\
static out_t name##_out_reg;\
name##_in = name##_in_reg;\
/*Defaults for single cycle pulses*/\
name##_in_reg.valid = 0;

// Assign read and write data words to mem map
// mostly for frame buffer IO type regs
// w/ .valid pulse, and rd,wr data fields, etc
#define VALID_PULSE_RW_DATA_WORD_MM_ENTRY(ADDR, name)\
else if(addr==ADDR){\
  o.addr_is_mapped = 1;\
  o.rd_data = name##_out_reg.rd_data;\
  name##_in_reg.valid = 1;\
  name##_in_reg.wr_en = wr_byte_ens[0];\
  if(wr_byte_ens[0]){\
    name##_in_reg.wr_data = wr_data;\
  }\
}

// IO types wrapped with FSM handshake signals
#define FSM_IO_TYPES_WRAPPER(name)\
typedef struct name##_in_valid_t{\
  name##_in_t data;\
  int32_t valid;\
}name##_in_valid_t;\
typedef struct name##_in_handshake_t{\
  name##_in_valid_t inputs;\
  int32_t output_ready;\
}name##_in_handshake_t;\
typedef struct name##_out_valid_t{\
  name##_out_t data;\
  int32_t valid;\
}name##_out_valid_t;\
typedef struct name##_out_handshake_t{\
  name##_out_valid_t outputs;\
  int32_t input_ready;\
}name##_out_handshake_t;

// Declare memory mapped function with
// input and output variables for a derived FSM
#define FSM_IN_MEM_MAP_VAR_DECL(name, in_t, IN_ADDR)\
static volatile in_t* name##_IN = (in_t*)IN_ADDR;
//
#define FSM_OUT_MEM_MAP_VAR_DECL(name, out_t, OUT_ADDR)\
static volatile out_t* name##_OUT = (out_t*)OUT_ADDR;
//
#define FSM_IO_MEM_MAP_VARS_DECL(name, out_t, OUT_ADDR, in_t, IN_ADDR)\
FSM_IN_MEM_MAP_VAR_DECL(name, in_t, IN_ADDR)\
FSM_OUT_MEM_MAP_VAR_DECL(name, out_t, OUT_ADDR)
//
#define FSM_MEM_MAP_FUNC_DECL(func_name, var_name)\
/* Variables */\
FSM_IO_MEM_MAP_VARS_DECL(\
  var_name,\
  func_name##_out_valid_t, var_name##_OUT_ADDR,\
  func_name##_in_valid_t, var_name##_IN_ADDR)\
/* Function version using memory mapped variables interface*/\
func_name##_out_t func_name(func_name##_in_t inputs){\
  /* Set input data without valid*/\
  var_name##_IN->data = inputs;\
  /* Set valid bit */\
  var_name##_IN->valid = 1;\
  /* (optionally wait for valid to be cleared indicating started work)*/\
  /* Then wait for valid output*/\
  while(var_name##_OUT->valid==0){}\
  /* Read output data*/\
  return var_name##_OUT->data;\
}

// Special case C function to use memory mapped input to derived FSM
// that does not use input struct, 2 inputs
#define FSM_MEM_MAP_VARS_FUNC_BODY_2INPUTS(name, out0, in0, in1)\
/* Set all input data*/\
name##_IN->data.in0 = in0;\
name##_IN->data.in1 = in1;\
/* Set valid bit */\
name##_IN->valid = 1;\
/* (optionally wait for valid to be cleared indicating started work)*/\
/* Then wait for valid output*/\
while(name##_OUT->valid==0){}\
/* Read outputs*/\
return name##_OUT->data.out0;

// Wrap up main FSM as top level
#define FSM_MAIN_IO_WRAPPER(name)\
MAIN(name##_wrapper)\
name##_INPUT_t name##_fsm_in;\
name##_OUTPUT_t name##_fsm_out;\
void name##_wrapper()\
{\
  name##_fsm_out = name##_FSM(name##_fsm_in);\
}

// Define IO regs and connect inputs for derived FSMs (with valid+ready handshake)
#define FSM_IN_REG_DECL(\
  name, in_t\
)\
/*IN regs connecting to FSM*/\
static in_t name##_in_reg;\
name##_fsm_in.input_valid = name##_in_reg.valid;\
name##_fsm_in.inputs = name##_in_reg.data;\
/*Clear input to fsm once accepted ready*/\
if(name##_fsm_out.input_ready){\
  name##_in_reg.valid = 0;\
}
//
#define FSM_OUT_REG_DECL(\
  name, out_t\
)/*OUT regs connecting to FSM*/\
static out_t name##_out_reg;
//
#define FSM_IO_REGS_DECL(name)\
FSM_IN_REG_DECL(name, name##_in_valid_t)\
FSM_OUT_REG_DECL(name, name##_out_valid_t)
//
#define FSM_IO_REGS_DECL_2INPUTS(\
  name, out_t,\
  in_t, input0, input1\
)\
/*IO regs connecting to FSM*/\
static in_t name##_in_reg;\
name##_fsm_in.input_valid = name##_in_reg.valid;\
name##_fsm_in.input0 = name##_in_reg.data.input0;\
name##_fsm_in.input1 = name##_in_reg.data.input1;\
/*Clear input to fsm once accepted ready*/\
if(name##_fsm_out.input_ready){\
  name##_in_reg.valid = 0;\
}\
FSM_OUT_REG_DECL(name, out_t)

// Assign derived FSM struct IO reg vars to memory map
#define FSM_IN_REG_STRUCT_MM_ENTRY(ADDR, in_t, name)\
STRUCT_MM_ENTRY(ADDR, in_t, name##_in_reg)
#define FSM_OUT_REG_STRUCT_MM_ENTRY(ADDR, out_t, name)\
STRUCT_MM_ENTRY(ADDR, out_t, name##_out_reg)
//
#define FSM_IO_REG_STRUCT_MM_ENTRY(addr_name, func_name)\
FSM_IN_REG_STRUCT_MM_ENTRY(addr_name##_IN_ADDR, func_name##_in_valid_t, func_name)\
FSM_OUT_REG_STRUCT_MM_ENTRY(addr_name##_OUT_ADDR, func_name##_out_valid_t, func_name)

// Connect outputs from derived FSMs (with valid+ready handshake) to regs
#define FSM_OUT_REG(name)\
name##_fsm_in.output_ready = 1;\
if(name##_fsm_in.input_valid & name##_fsm_out.input_ready){\
  /* Starting fsm clears output regs valid bit*/\
  name##_out_reg.valid = 0;\
}else if(name##_fsm_out.output_valid){\
  /* Output from FSM updated return values and sets valid flag*/\
  name##_out_reg.data = name##_fsm_out.return_output;\
  name##_out_reg.valid = 1;\
}
//
#define FSM_OUT_REG_1OUTPUT(name, out0)\
name##_fsm_in.output_ready = 1;\
if(name##_fsm_in.input_valid & name##_fsm_out.input_ready){\
  /* Starting fsm clears output regs valid bit*/\
  name##_out_reg.valid = 0;\
}else if(name##_fsm_out.output_valid){\
  /* Output from FSM updated return values and sets valid flag*/\
  name##_out_reg.data.out0 = name##_fsm_out.return_output;\
  name##_out_reg.valid = 1;\
}
