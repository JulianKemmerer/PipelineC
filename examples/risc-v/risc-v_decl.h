// TODO rename to single_cycle_risc-v_decl.h
#include "uintN_t.h"
#include "intN_t.h"

// Support old single core using mem_map_out_t
#include "mem_map.h"
#ifdef riscv_mem_map_outputs_t
#define riscv_mmio_mod_out_t riscv_mem_map_mod_out_t(riscv_mem_map_outputs_t)
#else
#define riscv_mmio_mod_out_t mem_map_out_t
#endif

// Declare instruction and data memory
// also includes memory mapped IO
#define RISCV_IMEM_0_CYCLE
#define RISCV_DMEM_0_CYCLE
#include "mem_decl.h"

// CPU top level
#define riscv_out_t PPCAT(riscv_name,_out_t)
typedef struct riscv_out_t{
  // Debug IO
  uint1_t halt;
  uint32_t return_value;
  uint32_t pc;
  uint1_t unknown_op;
  uint1_t mem_out_of_range;
  #ifdef riscv_mem_map_outputs_t
  riscv_mem_map_outputs_t mem_map_outputs;
  #endif
}riscv_out_t;
riscv_out_t riscv_name(
  // Optional inputs to memory map
  #ifdef riscv_mem_map_inputs_t
  riscv_mem_map_inputs_t mem_map_inputs
  #endif
)
{
  // Program counter
  static uint32_t pc = 0;
  uint32_t pc_plus4 = pc + 4;
  printf("PC = 0x%X\n", pc);

  // Instruction memory
  riscv_imem_ram_out_t imem_out = riscv_imem_ram(pc>>2, 1);

  // Decode the instruction to control signals
  printf("Instruction: 0x%X\n", imem_out.rd_data1);
  decoded_t decoded = decode(imem_out.rd_data1);

  // Register file reads and writes
  //  Register file write signals are not driven until later
  //  but are used now, requiring FEEDBACK pragma
  uint5_t reg_wr_addr;
  uint32_t reg_wr_data;
  uint1_t reg_wr_en;
  #pragma FEEDBACK reg_wr_addr
  #pragma FEEDBACK reg_wr_data
  #pragma FEEDBACK reg_wr_en  
  reg_file_out_t reg_file_out = reg_file(
    decoded.src1, // First read port address
    decoded.src2, // Second read port address
    reg_wr_addr, // Write port address
    reg_wr_data, // Write port data
    reg_wr_en // Write enable
  );
  if(decoded.print_rs1_read){
    printf("Read RegFile[%d] = %d\n", decoded.src1, reg_file_out.rd_data1);
  }
  if(decoded.print_rs2_read){
    printf("Read RegFile[%d] = %d\n", decoded.src2, reg_file_out.rd_data2);
  }

  // Execute
  execute_t exe = execute(
    pc, pc_plus4, 
    decoded, 
    reg_file_out.rd_data1, reg_file_out.rd_data2
  );

  // Data Memory
  uint32_t mem_addr = exe.result; // addr always from execute module, not always used
  uint32_t mem_wr_data = reg_file_out.rd_data2;
  uint1_t mem_wr_byte_ens[4] = decoded.mem_wr_byte_ens;
  uint1_t mem_rd_byte_ens[4] = decoded.mem_rd_byte_ens;
  riscv_dmem_out_t dmem_out = riscv_dmem(
    mem_addr, // Main memory read/write address
    mem_wr_data, // Main memory write data
    mem_wr_byte_ens, // Main memory write data byte enables
    mem_rd_byte_ens, // Main memory read enable
    1 // Single cycle always valid input every cycle
    // Optional memory map inputs
    #ifdef riscv_mem_map_inputs_t
    , mem_map_inputs
    #endif
  );
  if(decoded.mem_wr_byte_ens[0]){
    printf("Write Mem[0x%X] = %d\n", mem_addr, mem_wr_data);
  }
  if(decoded.mem_rd_byte_ens[0]){
    printf("Read Mem[0x%X] = %d\n", mem_addr, dmem_out.rd_data);
  }  

  // Reg file write back, drive inputs (FEEDBACK)
  reg_wr_en = decoded.reg_wr;
  reg_wr_addr = decoded.dest;
  // Determine reg data to write back (sign extend etc)
  reg_wr_data = select_reg_wr_data(
    decoded,
    exe,
    dmem_out.rd_data,
    pc_plus4
  );

  // Branch/Increment PC
  pc = select_next_pc(decoded, exe, pc_plus4);

  // Debug outputs
  riscv_out_t o;
  o.pc = pc;
  o.unknown_op = decoded.unknown_op;
  o.mem_out_of_range = dmem_out.mem_out_of_range;
  // Optional outputs from memory map
  #ifdef riscv_mem_map_outputs_t
  o.mem_map_outputs = dmem_out.mem_map_outputs;
  #endif
  return o;
}


#undef riscv_name
#undef RISCV_IMEM_SIZE_BYTES
#undef RISCV_DMEM_SIZE_BYTES
#undef RISCV_IMEM_NUM_WORDS
#undef RISCV_DMEM_NUM_WORDS
#undef RISCV_IMEM_INIT
#undef RISCV_DMEM_INIT
#undef riscv_mem_map
#undef riscv_mmio_mod_out_t
#undef riscv_mem_map_inputs_t
#undef riscv_mem_map_outputs_t
#undef riscv_imem_ram_out_t
#undef riscv_dmem_ram_out_t
#undef riscv_imem_ram
#undef riscv_dmem_ram
#undef riscv_imem_out_t
#undef riscv_dmem_out_t
#undef riscv_imem
#undef riscv_dmem