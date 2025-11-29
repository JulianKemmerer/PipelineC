#pragma once

// Helpers for building memory maps
// TODO move into risc-v.h?

// TODO move mm handshake macros to riscv mem map helper header?

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

// Little macro for stream() like vars made out of mem map u32s
#define MM_STREAM(type_t, name)\
type_t name;\
uint32_t name##_valid

// Handshake hardware helper macros

#define HANDSHAKE_MM_READ(regs, hs_name, stream_in, stream_ready_out)\
stream_ready_out = ~regs.hs_name##_valid;\
if(stream_ready_out & stream_in.valid){\
  regs.hs_name = stream_in.data;\
  regs.hs_name##_valid = 1;\
}

#define HANDSHAKE_MM_WRITE(stream_out, stream_ready_in, regs, hs_name)\
stream_out.data = regs.hs_name;\
stream_out.valid = regs.hs_name##_valid;\
if(stream_out.valid & stream_ready_in){\
    regs.hs_name##_valid = 0;\
}

// Read handshake helper macros

#define mm_handshake_read(out_ptr, hs_name) \
/* Wait for valid data to show up */ \
while(!mm_regs->hs_name##_valid){} \
/* Copy the data to output */ \
*(out_ptr) = mm_regs->hs_name; \
/* Signal done with data */ \
mm_regs->hs_name##_valid = 0

#define mm_handshake_try_read(success_ptr, out_ptr, hs_name) \
*(success_ptr) = 0;\
if(mm_regs->hs_name##_valid){\
  /* Copy the data to output */ \
  *(out_ptr) = mm_regs->hs_name; \
  /* Signal done with data */ \
  mm_regs->hs_name##_valid = 0;\
  /* Set success */ \
  *(success_ptr) = 1;\
}

// Write handshake helper macro
#define mm_handshake_write(hs_name, in_ptr) \
/* Wait for buffer to be invalid=empty */\
while(mm_regs->hs_name##_valid){} \
/* Put input data into data reg */ \
mm_regs->hs_name = *in_ptr; \
/* Signal data is valid now */ \
mm_regs->hs_name##_valid = 1;


// Helper macros to reduce code in and around mem_map_module

// Map 4 byte array to a word index
#define BYTES4_MM_WRITE_LOGIC(\
  WORD_INDEX, reg_bytes,\
  word_index_var, wr_bytes_in, wr_byte_ens\
)\
if(word_index_var==WORD_INDEX){\
  for(uint32_t BYTES4_MM_LOGIC_i=0;BYTES4_MM_LOGIC_i<4;BYTES4_MM_LOGIC_i+=1){\
    if(wr_byte_ens[BYTES4_MM_LOGIC_i]){\
      reg_bytes[BYTES4_MM_LOGIC_i] = wr_bytes_in[BYTES4_MM_LOGIC_i];\
    }\
  }\
}

// Assign a struct variable to the memory map
// assumes address constants and variables are 32b | four byte word aligned
#define STRUCT_MM_ENTRY_NEWEST(\
  enabled, ADDR, type_t, struct_out, struct_in,\
  addr_var, wr_word_in, wr_byte_ens, addr_is_mapped, rd_word_out\
)\
if(enabled){/* (addr_var>=ADDR) & (addr_var<(ADDR+sizeof(type_t)))TODO reduce width of math here too, do sub to get to off range then compare on that?*/\
  /*addr_is_mapped = 1;*/\
  /* Convert to bytes*/\
  type_t##_bytes_t type_t##_byte_array = type_t##_to_bytes(struct_in);\
  /* Convert to 4 byte words*/\
  /* TODO didnt make difference? use smaller int types for addrs/offsets since structs arent that big? */\
  uint14_t STRUCT_MM_ENTRY_word_var = addr_var >> 2;\
  uint14_t STRUCT_MM_ENTRY_WORD_INDEX = ADDR >> 2;\
  uint14_t STRUCT_MM_ENTRY_word_offset = STRUCT_MM_ENTRY_word_var - STRUCT_MM_ENTRY_WORD_INDEX;\
  uint8_t STRUCT_MM_ENTRY_wr_bytes_in[4];\
  UINT_TO_BYTE_ARRAY(STRUCT_MM_ENTRY_wr_bytes_in, 4, wr_word_in)\
  uint8_t type_t##_word_bytes[sizeof(type_t)/4][4];\
  for(uint32_t STRUCT_MM_ENTRY_word_i = 0; STRUCT_MM_ENTRY_word_i < (sizeof(type_t)/4); STRUCT_MM_ENTRY_word_i+=1){\
    uint32_t STRUCT_MM_ENTRY_byte_offset = STRUCT_MM_ENTRY_word_i*4;\
    for(uint32_t STRUCT_MM_ENTRY_byte_i=0;STRUCT_MM_ENTRY_byte_i<4;STRUCT_MM_ENTRY_byte_i+=1){\
      type_t##_word_bytes[STRUCT_MM_ENTRY_word_i][STRUCT_MM_ENTRY_byte_i] = type_t##_byte_array.data[STRUCT_MM_ENTRY_byte_offset+STRUCT_MM_ENTRY_byte_i];\
    }\
  }\
  /* Select word for read back */\
  rd_word_out = uint8_array4_le(type_t##_word_bytes[STRUCT_MM_ENTRY_word_offset]);\
  /* Do byte write enables per word */\
  for(uint32_t STRUCT_MM_ENTRY_word_i = 0; STRUCT_MM_ENTRY_word_i < (sizeof(type_t)/4); STRUCT_MM_ENTRY_word_i+=1){\
    /* mem map each 4 byte word */\
    uint8_t STRUCT_MM_ENTRY_selected_word_bytes[4] = type_t##_word_bytes[STRUCT_MM_ENTRY_word_i];\
    BYTES4_MM_WRITE_LOGIC(\
      (STRUCT_MM_ENTRY_WORD_INDEX + STRUCT_MM_ENTRY_word_i),\
      STRUCT_MM_ENTRY_selected_word_bytes,\
      STRUCT_MM_ENTRY_word_offset,\
      STRUCT_MM_ENTRY_wr_bytes_in,\
      wr_byte_ens\
    )\
    type_t##_word_bytes[STRUCT_MM_ENTRY_word_i] = STRUCT_MM_ENTRY_selected_word_bytes;\
  }\
  /* Convert back to bytes then back to struct */\
  for(uint32_t STRUCT_MM_ENTRY_word_i = 0; STRUCT_MM_ENTRY_word_i < (sizeof(type_t)/4); STRUCT_MM_ENTRY_word_i+=1){\
    uint32_t STRUCT_MM_ENTRY_byte_offset = STRUCT_MM_ENTRY_word_i*4;\
    for(uint32_t STRUCT_MM_ENTRY_byte_i=0;STRUCT_MM_ENTRY_byte_i<4;STRUCT_MM_ENTRY_byte_i+=1){\
      type_t##_byte_array.data[STRUCT_MM_ENTRY_byte_offset+STRUCT_MM_ENTRY_byte_i] = type_t##_word_bytes[STRUCT_MM_ENTRY_word_i][STRUCT_MM_ENTRY_byte_i];\
    }\
  }\
  struct_out = bytes_to_##type_t(type_t##_byte_array);\
}




// OLD VERSION
#define STRUCT_MM_ENTRY_NEW(\
ADDR, type_t, wr_out, rd_in, \
addr_var, addr_is_mapped, rd_out)\
if( (addr_var>=ADDR) & (addr_var<(ADDR+sizeof(type_t))) ){\
  /*addr_is_mapped = 1;*/\
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
