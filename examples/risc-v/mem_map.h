#pragma once

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

// Define IO regs and connect inputs with single cycle .valid field
#define VALID_PULSE_IO_REGS_DECL(name, out_t, in_t)\
/*In+out registers for wires, for better fmax*/\
static in_t name##_in_reg;\
static out_t name##_out_reg;\
name##_in = name##_in_reg;\
/*Defaults for single cycle pulses*/\
name##_in_reg.valid = 0;

// Assign input register word to mem map
#define IN_REG_WORD_MM_ENTRY(ADDR, name, field)\
WORD_MM_ENTRY(ADDR, name##_in_reg.field)

// Connect outputs to registers for better fmax
#define OUT_REG(name)\
name##_out_reg = name##_out;

// Assign data word to mem map that works with IO regs and valid pulse
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

// Fields for derived FSM input struct type
#define FSM_IN_TYPE_FIELDS \
int32_t valid;
//
#define FSM_IN_TYPE_FIELDS_2INPUTS(in0_t, in0, in1_t, in1)\
FSM_IN_TYPE_FIELDS \
in0_t in0;\
in1_t in1;

// Fields for derived FSM output struct type
#define FSM_OUT_TYPE_FIELDS \
int32_t valid;

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
  func_name##_out_t, var_name##_OUT_ADDR,\
  func_name##_in_t, var_name##_IN_ADDR)\
/* Function version using memory mapped variables interface*/\
func_name##_out_t func_name(func_name##_in_t inputs){\
  /* Set input value without valid*/\
  inputs.valid = 0;\
  *var_name##_IN = inputs;\
  /* Set valid bit */\
  var_name##_IN->valid = 1;\
  /* (optionally wait for valid to be cleared indicating started work)*/\
  /* Then wait for valid output*/\
  while(var_name##_OUT->valid==0){}\
  /* Read outputs*/\
  return *var_name##_OUT;\
}


// Contents of C function to use memory mapped input and output variables for a derived FSM
#define FSM_MEM_MAP_VARS_FUNC_BODY_2INPUTS(name, out0, in0, in1)\
/* Set all input values*/\
name##_IN->in0 = in0;\
name##_IN->in1 = in1;\
/* Set valid bit */\
name##_IN->valid = 1;\
/* (optionally wait for valid to be cleared indicating started work)*/\
/* Then wait for valid output*/\
while(name##_OUT->valid==0){}\
/* Read outputs*/\
return name##_OUT->out0;

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
name##_fsm_in.inputs = name##_in_reg;\
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
FSM_IN_REG_DECL(name, name##_in_t)\
FSM_OUT_REG_DECL(name, name##_out_t)
//
#define FSM_IO_REGS_DECL_2INPUTS(\
  name, out_t,\
  in_t, input0, input1\
)\
/*IO regs connecting to FSM*/\
static in_t name##_in_reg;\
name##_fsm_in.input_valid = name##_in_reg.valid;\
name##_fsm_in.input0 = name##_in_reg.input0;\
name##_fsm_in.input1 = name##_in_reg.input1;\
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
FSM_IN_REG_STRUCT_MM_ENTRY(addr_name##_IN_ADDR, func_name##_in_t, func_name)\
FSM_OUT_REG_STRUCT_MM_ENTRY(addr_name##_OUT_ADDR, func_name##_out_t, func_name)

// Connect outputs from derived FSMs (with valid+ready handshake) to regs
#define FSM_OUT_REG(name)\
name##_fsm_in.output_ready = 1;\
if(name##_fsm_in.input_valid & name##_fsm_out.input_ready){\
  /* Starting fsm clears output regs valid bit*/\
  name##_out_reg.valid = 0;\
}else if(name##_fsm_out.output_valid){\
  /* Output from FSM updated return values and sets valid flag*/\
  name##_out_reg = name##_fsm_out.return_output;\
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
  name##_out_reg.out0 = name##_fsm_out.return_output;\
  name##_out_reg.valid = 1;\
}


// Hardware memory address mappings

#ifdef __PIPELINEC__
#include "compiler.h"
#include "uintN_t.h"
#else
#include <stdint.h>
#endif

#define MEM_MAP_BASE_ADDR 0x10000000 

// The output/stop/halt peripheral
#define RETURN_OUTPUT_ADDR (MEM_MAP_BASE_ADDR+0)
static volatile uint32_t* RETURN_OUTPUT = (uint32_t*)RETURN_OUTPUT_ADDR;

// LEDs
#define LEDS_ADDR (RETURN_OUTPUT_ADDR + sizeof(uint32_t))
static volatile uint32_t* LEDS = (uint32_t*)LEDS_ADDR;

// Re: memory mapped structs
//__attribute__((packed)) increases code size bringing in memcpy
// Not actually needed to pack for ~memory savings
// when memory mapped padding regs will optimize away if unused
// So manually add padding fields for 32b|4B alignment (otherwise need packed)
// (if not PipelineC built in to-from bytes functions won't work)

// For now use separate input and output structs for accelerators
// that have special input and output valid flags
#include "gcc_test/gol/hw_config.h"