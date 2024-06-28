// TODO rename defined things to be MULTI_CYCLE_RISCV_... etc
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
#define RISCV_IMEM_1_CYCLE
#define RISCV_DMEM_1_CYCLE
// Multi cycle is not a pipeline
#define RISCV_IMEM_NO_AUTOPIPELINE
#define RISCV_DMEM_NO_AUTOPIPELINE
#define N_CYCLES 3
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
  // Top level outputs
  riscv_out_t o;

  // Instead of a counter for which stage is active
  // one hot bit is easier to work with (especially come time for pipelining)
  static uint1_t stage_valid[N_CYCLES] = {[0]=1}; // Starts in stage_valid[0]
  uint1_t next_stage_valid[N_CYCLES]; // Update static reg at end of func
  
  // CPU registers (outside of reg file)
  static uint32_t pc = 0;
  o.pc = pc; // debug
  //  Wires/non-static local variables from original single cycle design
  //  are likely to be shared/stored from cycle to cycle now
  //  so just declare all (non-FEEDBACK) local variables static registers too
  static uint32_t pc_plus4;
  static riscv_imem_ram_out_t imem_out;
  static decoded_t decoded;
  static reg_file_out_t reg_file_out;
  static execute_t exe;
  static uint1_t mem_wr_byte_ens[4];
  static uint1_t mem_rd_byte_ens[4];
  static uint32_t mem_addr;
  static uint32_t mem_wr_data;
  static riscv_dmem_out_t dmem_out;
  
  // Cycle 0: PC
  if(stage_valid[0]){
    printf("PC in Cycle/Stage 0\n");
    // Program counter is input to IMEM
    pc_plus4 = pc + 4;
    printf("PC = 0x%X\n", pc);
    // Next state/cycle (potentially redundant)
    next_stage_valid = stage_valid;
    ARRAY_1ROT_UP(uint1_t, next_stage_valid, N_CYCLES)
  }

  // Boundary shared between cycle0 and cycle1
  if(stage_valid[0]|stage_valid[1]){
    // Instruction memory
    imem_out = riscv_imem_ram(pc>>2, 1);
  }

  // Cycle1: Decode
  if(stage_valid[1]){
    printf("Decode in Cycle/Stage 1\n");
    // Decode the instruction to control signals
    printf("Instruction: 0x%X\n", imem_out.rd_data1);
    decoded = decode(imem_out.rd_data1);
    if(decoded.print_rs1_read){
      printf("Read RegFile[%d] = %d\n", decoded.src1, reg_file_out.rd_data1);
    }
    if(decoded.print_rs2_read){
      printf("Read RegFile[%d] = %d\n", decoded.src2, reg_file_out.rd_data2);
    }
    o.unknown_op = decoded.unknown_op; // debug
    // Next state/cycle (potentially redundant)
    next_stage_valid = stage_valid;
    ARRAY_1ROT_UP(uint1_t, next_stage_valid, N_CYCLES)
  }

  // Cycle1+2: Register file reads and writes
  //  Reads are done during cycle1
  //  Write back is next clock, cycle2
  //  Register file write signals are not driven until later in code
  //  but are used now, requiring FEEDBACK pragma
  uint5_t reg_wr_addr;
  uint32_t reg_wr_data;
  uint1_t reg_wr_en;
  #pragma FEEDBACK reg_wr_addr
  #pragma FEEDBACK reg_wr_data
  #pragma FEEDBACK reg_wr_en 
  if(stage_valid[1]|stage_valid[2]){
    reg_file_out = reg_file(
      decoded.src1, // First read port address
      decoded.src2, // Second read port address
      reg_wr_addr, // Write port address
      reg_wr_data, // Write port data
      reg_wr_en // Write enable
    );
    // Next state/cycle (potentially redundant)
    next_stage_valid = stage_valid;
    ARRAY_1ROT_UP(uint1_t, next_stage_valid, N_CYCLES)
  }
  
  // Cycle1: Execute
  if(stage_valid[1]){
    printf("Execute in Cycle/Stage 1\n");
    exe = execute(
      pc, pc_plus4, 
      decoded, 
      reg_file_out.rd_data1, reg_file_out.rd_data2
    );
    // Next state/cycle (potentially redundant)
    next_stage_valid = stage_valid;
    ARRAY_1ROT_UP(uint1_t, next_stage_valid, N_CYCLES)
  }

  // Boundary shared between cycle1 and cycle2
  // Data Memory inputs in stage1
  // Default no writes or reads
  ARRAY_SET(mem_wr_byte_ens, 0, 4)
  ARRAY_SET(mem_rd_byte_ens, 0, 4)
  uint32_t mem_addr = exe.result; // addr always from execute module, not always used
  uint32_t mem_wr_data = reg_file_out.rd_data2;
  if(stage_valid[1]){
    // Only write or read en during first cycle of two cycle read
    mem_wr_byte_ens = decoded.mem_wr_byte_ens;
    mem_rd_byte_ens = decoded.mem_rd_byte_ens;
    if(decoded.mem_wr_byte_ens[0]){
      printf("Write Mem[0x%X] = %d\n", mem_addr, mem_wr_data);
    }
  }
  // DMEM always "in use" regardless of stage
  // since memory map IO need to be connected always
  dmem_out = riscv_dmem(
    mem_addr, // Main memory read/write address
    mem_wr_data, // Main memory write data
    mem_wr_byte_ens, // Main memory write data byte enables
    mem_rd_byte_ens // Main memory read enable
    // Optional memory map inputs
    #ifdef riscv_mem_map_inputs_t
    , mem_map_inputs
    #endif
  );
  o.mem_out_of_range = dmem_out.mem_out_of_range; // debug
  // Optional outputs from memory map
  #ifdef riscv_mem_map_outputs_t
  o.mem_map_outputs = dmem_out.mem_map_outputs;
  #endif
  // Data memory outputs in stage2
  if(stage_valid[2]){
    // Read output available from dmem_out in second cycle of two cycle read
    if(decoded.mem_rd_byte_ens[0]){
      printf("Read Mem[0x%X] = %d\n", mem_addr, dmem_out.rd_data);
    }
  }

  // Cycle 2: Write Back + Next PC
  // default values needed for feedback signals
  reg_wr_en = 0; // default no writes 
  reg_wr_addr = 0;
  reg_wr_data = 0;
  if(stage_valid[2]){
    printf("Write Back + Next PC in Cycle/Stage 2\n");
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
    // Next state/cycle (potentially redundant)
    next_stage_valid = stage_valid;
    ARRAY_1ROT_UP(uint1_t, next_stage_valid, N_CYCLES)
  }

  // Reg update
  stage_valid = next_stage_valid;
  
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
#undef RISCV_IMEM_NO_AUTOPIPELINE
#undef RISCV_DMEM_NO_AUTOPIPELINE
