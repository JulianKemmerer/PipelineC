#pragma once

// Helpers for building memory maps
// TODO move into risc-v.h?

// TODO move mm handshake macros to riscv mem map helper header?

// Read handshake helper macros

#define mm_handshake_read(out_ptr, hs_name) \
/* Wait for valid data to show up */ \
while(!mm_handshake_valid->hs_name){} \
/* Copy the data to output */ \
*(out_ptr) = mm_handshake_data->hs_name; \
/* Signal done with data */ \
mm_handshake_valid->hs_name = 0

#define mm_handshake_try_read(success_ptr, out_ptr, hs_name) \
*(success_ptr) = 0;\
if(mm_handshake_valid->hs_name){\
  /* Copy the data to output */ \
  *(out_ptr) = mm_handshake_data->hs_name; \
  /* Signal done with data */ \
  mm_handshake_valid->hs_name = 0;\
  /* Set success */ \
  *(success_ptr) = 1;\
}

// Write hanshake helper macro
#define mm_handshake_write(hs_name, in_ptr) \
/* Wait for buffer to be invalid=empty */\
while(mm_handshake_valid->hs_name){} \
/* Put input data into data reg */ \
mm_handshake_data->hs_name = *in_ptr; \
/* Signal data is valid now */ \
mm_handshake_valid->hs_name = 1;

// Base/default version without user types
typedef struct mem_map_out_t
{
  uint1_t addr_is_mapped;
  uint32_t rd_data;
}mem_map_out_t;

// Base struct builder helper with user types
#define riscv_mem_map_mod_out_t(mem_map_outputs_t)\
PPCAT(mem_map_outputs_t,_riscv_mem_map_mod_out_t)

#define RISCV_DECL_MEM_MAP_MOD_OUT_T(mem_map_outputs_t)\
typedef struct riscv_mem_map_mod_out_t(mem_map_outputs_t)\
{\
  uint1_t addr_is_mapped;\
  uint32_t rd_data;\
  uint1_t valid;/*done, aka rd_data valid*/\
  uint1_t ready_for_inputs;\
  mem_map_outputs_t outputs;\
}riscv_mem_map_mod_out_t(mem_map_outputs_t);

#define RISCV_MEM_MAP_MOD_INPUTS(mem_map_inputs_t)\
uint32_t addr,\
uint32_t wr_data, uint1_t wr_byte_ens[4],\
uint1_t rd_byte_ens[4],\
uint1_t valid,/*aka start*/\
uint1_t ready_for_outputs,\
mem_map_inputs_t inputs


// Helper macros to reduce code in and around mem_map_module
//  TODO: Make read-write struct byte array muxing simpler, not all alignments handled are possible.

// Assign a word variable to the memory map
#define WORD_MM_ENTRY(o, ADDR, var)\
if(addr==ADDR){\
  o.addr_is_mapped = 1;\
  o.rd_data = var;\
  if(wr_byte_ens[0]){\
    var = wr_data;\
  }\
}

// Assign a struct variable to the memory map
#define STRUCT_MM_ENTRY(o, ADDR, type_t, var)\
if( (addr>=ADDR) & (addr<(ADDR+sizeof(type_t))) ){\
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
WORD_MM_ENTRY(o, ADDR, name##_in_reg.field)

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
if(addr==ADDR){\
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



// New version of above macros thats more flexible 
///... eventually and uses less resources for large structs
// Assign a struct variable to the memory map
#define STRUCT_MM_ENTRY_NEW(\
ADDR, type_t, wr_out, rd_in, \
addr_var, addr_is_mapped, rd_out)\
if( (addr_var>=ADDR) & (addr_var<(ADDR+sizeof(type_t))) ){\
  addr_is_mapped = 1;\
  /* Convert to bytes*/\
  type_t##_bytes_t type_t##_byte_array = type_t##_to_bytes(rd_in);\
  uint32_t type_t##_bytes_offset = addr_var - ADDR;\
  /* Assemble rd data bytes*/\
  uint32_t type_t##_byte_i;\
  uint8_t type_t##_rd_bytes[4];\
  for(type_t##_byte_i=0;type_t##_byte_i<4;type_t##_byte_i+=1){\
    type_t##_rd_bytes[type_t##_byte_i] = type_t##_byte_array.data[type_t##_bytes_offset+type_t##_byte_i];\
  }\
  rd_out = uint8_array4_le(type_t##_rd_bytes);\
  /* Drive write bytes*/\
  for(type_t##_byte_i=0;type_t##_byte_i<4;type_t##_byte_i+=1){\
    if(wr_byte_ens[type_t##_byte_i]){\
      type_t##_byte_array.data[type_t##_bytes_offset+type_t##_byte_i] = wr_data >> (type_t##_byte_i*8);\
    }\
  }\
  /* Convert back to type*/\
  wr_out = bytes_to_##type_t(type_t##_byte_array);\
}
// Assign a word variable to the memory map // TODO other byte alignments?
#define WORD_MM_ENTRY_NEW(ADDR, wr_out, rd_in, addr_var, addr_is_mapped, rd_out)\
if(addr_var==ADDR){\
  addr_is_mapped = 1;\
  rd_out = rd_in;\
  if(wr_byte_ens[0]){\
    wr_out = wr_data;\
  }\
}

#define HANDSHAKE_MM_READ(hs_data_reg, hs_valid_reg, hs_data_name, stream_in, stream_ready_out)\
stream_ready_out = ~hs_valid_reg.hs_data_name;\
if(stream_ready_out & stream_in.valid){\
  hs_data_reg.hs_data_name = stream_in.data;\
  hs_valid_reg.hs_data_name = 1;\
}

#define HANDSHAKE_MM_WRITE(stream_out, stream_ready_in, hs_data_reg, hs_valid_reg, hs_data_name)\
stream_out.data = hs_data_reg.hs_data_name;\
stream_out.valid = hs_valid_reg.hs_data_name;\
if(stream_out.valid & stream_ready_in){\
    hs_valid_reg.hs_data_name = 0;\
}
