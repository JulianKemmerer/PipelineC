// Started with copy of old fft_risc-v.c from risc-v/ examples dir
// RISCV CPU, FSM that takes multiple cycles
// uses autopipelines for some stages

// RISC-V components
// For now hard coded flags to enable different extensions
//#define RV32_M
#define RISCV_REGFILE_1_CYCLE
#include "risc-v/risc-v.h"

// Declare instruction and data memory with gcc compiled program
// also includes memory mapped IO
#include "../software/text_mem_init.h"
#include "../software/data_mem_init.h"
#define riscv_name fsm_riscv
#define RISCV_IMEM_INIT         text_MEM_INIT // from software/
#define RISCV_IMEM_SIZE_BYTES   IMEM_SIZE     // from software/
#define RISCV_DMEM_INIT         data_MEM_INIT // from software/
#define RISCV_DMEM_SIZE_BYTES   DMEM_SIZE     // from software/
#define riscv_mem_map           my_mem_map_module
#define riscv_mem_map_inputs_t  my_mmio_in_t
#define riscv_mem_map_outputs_t my_mmio_out_t
#define RISCV_IMEM_1_CYCLE
#define RISCV_DMEM_1_CYCLE
// Multi cycle is not a pipeline
#define RISCV_IMEM_NO_AUTOPIPELINE
#define RISCV_DMEM_NO_AUTOPIPELINE
#include "risc-v/mem_decl.h"

// Declare globally visible auto pipelines out of exe logic
#include "global_func_inst.h"
//  Global function has no built in delay, can 'return' in same cycle
GLOBAL_FUNC_INST_W_VALID_ID(execute_rv32i_pipeline, execute_t, execute_rv32i, execute_rv32i_in_t) 
#ifdef RV32_M
//  Global pipeline has built in minimum 2 cycle delay for input and output regs
GLOBAL_PIPELINE_INST_W_VALID_ID(execute_rv32_mul_pipeline, execute_t, execute_rv32_mul, execute_rv32_m_ext_in_t)
GLOBAL_PIPELINE_INST_W_VALID_ID(execute_rv32_div_pipeline, execute_t, execute_rv32_div, execute_rv32_m_ext_in_t)
#endif

// Not all states take an entire cycle,
// i.e. EXE_END to MEM_START is same cycle
//      MEM_END to WRITE_BACK_NEXT_PC is same cycle
// TODO switch to one_hot.h helper lib for state
typedef enum cpu_state_t{
  // Use PC as addr into IMEM
  FETCH_START, 
  // Get instruction from IMEM, decode it, supply regfile read addresses
  FETCH_END_DECODE_REG_RD_START,
  // Use read data from regfile for execute start
  REG_RD_END_EXE_START,
  // Wait for output data from execute,
  EXE_END,
  //     \/ SAME CYCLE \/
  // Data into dmem starting mem transaction
  MEM_START,
  // Wait for DMEM mem transfer to finish
  MEM_END,
  //     \/ SAME CYCLE \/
  // Write back, update to next pc
  WRITE_BACK_NEXT_PC,
  // Debug error state to halt execution
  WTF
}cpu_state_t;

// CPU top level
typedef struct riscv_out_t{
  // Debug IO
  uint1_t halt;
  uint32_t return_value;
  uint32_t pc;
  uint1_t unknown_op;
  uint1_t mem_out_of_range;
  uint1_t pc_out_of_range;
  riscv_mem_map_outputs_t mem_map_outputs;
}riscv_out_t;
riscv_out_t fsm_riscv(
  uint1_t reset,
  riscv_mem_map_inputs_t mem_map_inputs
)
{
  // Top level outputs
  riscv_out_t o;

  // CPU multi cycle state reg
  static cpu_state_t state = FETCH_START;
  cpu_state_t next_state = state; // Update static reg at end of func
  
  // CPU registers (outside of reg file)
  static uint32_t pc = 0;
  o.pc = pc; // debug
  //  Wires/non-static local variables from original single cycle design
  //  are likely to be shared/stored from cycle to cycle now
  //  so just declare all (non-FEEDBACK) local variables static registers too
  static uint32_t pc_plus4_reg;
  static riscv_imem_ram_out_t imem_out_reg;
  static decoded_t decoded_reg;
  static reg_file_out_t reg_file_out_reg;
  static execute_t exe_reg;
  static uint1_t mem_wr_byte_ens_reg[4];
  static uint1_t mem_rd_byte_ens_reg[4];
  static uint32_t mem_addr_reg;
  static uint32_t mem_wr_data_reg;
  static uint1_t mem_valid_in_reg;
  static riscv_dmem_out_t dmem_out_reg;
  // But still have non-static wires version of registers too
  // to help avoid/resolve unintentional passing of data between stages
  // in the same cycle (like single cycle cpu did)
  uint32_t pc_plus4 = pc_plus4_reg;
  riscv_imem_ram_out_t imem_out = imem_out_reg;
  decoded_t decoded = decoded_reg;
  reg_file_out_t reg_file_out = reg_file_out_reg;
  execute_t exe = exe_reg;
  uint1_t mem_wr_byte_ens[4] = mem_wr_byte_ens_reg;
  uint1_t mem_rd_byte_ens[4] = mem_rd_byte_ens_reg;
  uint32_t mem_addr = mem_addr_reg;
  uint32_t mem_wr_data = mem_wr_data_reg;
  uint1_t mem_valid_in = mem_valid_in_reg;
  riscv_dmem_out_t dmem_out = dmem_out_reg;
  
  // PC fetch
  if(state==FETCH_START){
    printf("PC FETCH_START\n");
    // Program counter is input to IMEM
    pc_plus4 = pc + 4;
    printf("PC = 0x%X\n", pc);
    next_state = FETCH_END_DECODE_REG_RD_START;
  }

  // Boundary shared between fetch and decode
  // Instruction memory
  imem_out = riscv_imem_ram(pc>>2, 1);
  if((pc>>2) >= RISCV_IMEM_NUM_WORDS){
    o.pc_out_of_range = 1;
  }

  // Decode
  if(state==FETCH_END_DECODE_REG_RD_START){
    printf("Decode:\n");
    // Decode the instruction to control signals
    printf("Instruction: 0x%X\n", imem_out.rd_data1);
    decoded = decode(imem_out.rd_data1);
    o.unknown_op = decoded.unknown_op; // debug
    next_state = REG_RD_END_EXE_START;
  }

  // TODO dont gate data signals (have default assignment)
  // only the enable/valid signal needs gating (ex, reg_wr_en vs reg_wr_data/addr)

  // Register file reads and writes
  //  Register file write signals are not driven until later in code
  //  but are used now, requiring FEEDBACK pragma
  uint5_t reg_wr_addr;
  uint32_t reg_wr_data;
  uint1_t reg_wr_en;
  #pragma FEEDBACK reg_wr_addr
  #pragma FEEDBACK reg_wr_data
  #pragma FEEDBACK reg_wr_en
  reg_file_out = reg_file(
    decoded.src1, // First read port address
    decoded.src2, // Second read port address
    reg_wr_addr, // Write port address
    reg_wr_data, // Write port data
    reg_wr_en // Write enable
  );
  if(state==REG_RD_END_EXE_START){
    if(decoded_reg.print_rs1_read){
      printf("Read RegFile[%d] = %d\n", decoded_reg.src1, reg_file_out.rd_data1);
    }
    if(decoded_reg.print_rs2_read){
      printf("Read RegFile[%d] = %d\n", decoded_reg.src2, reg_file_out.rd_data2);
    }
  }

  // Execute start
  // Default no data into pipelines
  execute_rv32i_pipeline_in_valid = 0;
  #ifdef RV32_M
  execute_rv32_mul_pipeline_in_valid = 0;
  execute_rv32_div_pipeline_in_valid = 0;
  #endif
  if(state==REG_RD_END_EXE_START){
    // Which EXE pipeline to put input into?
    if(decoded_reg.is_rv32i){
      // RV32I
      printf("RV32I Execute Start:\n");
      execute_rv32i_pipeline_in.pc = pc;
      execute_rv32i_pipeline_in.pc_plus4 = pc_plus4_reg;
      execute_rv32i_pipeline_in.decoded = decoded_reg;
      execute_rv32i_pipeline_in.reg1 = reg_file_out.rd_data1;
      execute_rv32i_pipeline_in.reg2 = reg_file_out.rd_data2;
      execute_rv32i_pipeline_in_valid = 1;
      // RV32I might not need pipelining, so allow same cycle execution
      // (same cycle as if in-line execute() called here)
      state = EXE_END; next_state = state; // SAME CYCLE STATE TRANSITION
    }
    #ifdef RV32_M
    else if(decoded_reg.is_rv32_mul){
      // MUL
      printf("RV32 MUL Execute Start:\n");
      execute_rv32_mul_pipeline_in.decoded = decoded_reg;
      execute_rv32_mul_pipeline_in.reg1 = reg_file_out.rd_data1;
      execute_rv32_mul_pipeline_in.reg2 = reg_file_out.rd_data2;
      execute_rv32_mul_pipeline_in_valid = 1;
      // Start waiting for a valid output (next cycle)
      next_state = EXE_END;  
    }else if(decoded_reg.is_rv32_div){
      // DIV+REM
      printf("RV32 DIV|REM Execute Start:\n");
      execute_rv32_div_pipeline_in.decoded = decoded_reg;
      execute_rv32_div_pipeline_in.reg1 = reg_file_out.rd_data1;
      execute_rv32_div_pipeline_in.reg2 = reg_file_out.rd_data2;
      execute_rv32_div_pipeline_in_valid = 1;
      // Start waiting for a valid output (next cycle)
      next_state = EXE_END;
    }
    #endif
  }
  // Execute finish
  if(state==EXE_END){
    // What is next state? Can skip dmem maybe to write back directly?
    cpu_state_t exe_next_state = WRITE_BACK_NEXT_PC;
    if(decoded_reg.reg_to_mem | decoded_reg.mem_to_reg){
      exe_next_state = MEM_START; // cant skip dmem
    }
    // Which EXE pipeline to wait for valid output from?
    // Then move on to next state
    if(decoded_reg.is_rv32i){
      // RV32I
      printf("Waiting for RV32I Execute to end...\n");
      if(execute_rv32i_pipeline_out_valid){
        printf("RV32I Execute End:\n");
        exe = execute_rv32i_pipeline_out;
        state = exe_next_state; next_state = state; // SAME CYCLE STATE TRANSITION
      }
    }
    #ifdef RV32_M
    else if(decoded_reg.is_rv32_mul){
      // MUL
      printf("Waiting for RV32 MUL Execute to end...\n");
      if(execute_rv32_mul_pipeline_out_valid){
        printf("RV32 MUL Execute End:\n");
        exe = execute_rv32_mul_pipeline_out;
        state = exe_next_state; next_state = state; // SAME CYCLE STATE TRANSITION
      }
    }else if(decoded_reg.is_rv32_div){
      // DIV|REM
      printf("Waiting for RV32 DIV|REM Execute to end...\n");
      if(execute_rv32_div_pipeline_out_valid){
        printf("RV32 DIV|REM Execute End:\n");
        exe = execute_rv32_div_pipeline_out;
        state = exe_next_state; next_state = state; // SAME CYCLE STATE TRANSITION
      }
    }
    #endif
  }

  // Boundary shared between exe and dmem
  // Drive dmem inputs:
  // Default no writes or reads
  mem_valid_in = 0;
  ARRAY_SET(mem_wr_byte_ens, 0, 4)
  ARRAY_SET(mem_rd_byte_ens, 0, 4)  
  mem_addr = 0;
  mem_wr_data = 0;
  if(state==MEM_START){
    printf("Starting MEM...\n");
    mem_addr = exe.result; // Driven somewhere in EXE_END above^
    mem_wr_data = reg_file_out.rd_data2; // direct from regfile since could be same cycle rv32i exe
    mem_wr_byte_ens = decoded_reg.mem_wr_byte_ens;
    mem_rd_byte_ens = decoded_reg.mem_rd_byte_ens;
    mem_valid_in = 1;
    if(mem_wr_byte_ens[0]){
      printf("Write Mem[0x%X] = %d started\n", mem_addr, mem_wr_data);
    }
    if(mem_rd_byte_ens[0]){
      printf("Read Mem[0x%X] started\n", mem_addr);
    }
    // Transition out of MEM_START state handled after dmem below, needs output ready signal
  }
  // DMEM always "in use" regardless of stage
  // since memory map IO need to be connected always
  dmem_out = riscv_dmem(
    mem_addr, // Main memory read/write address
    mem_wr_data, // Main memory write data
    mem_wr_byte_ens, // Main memory write data byte enables
    mem_rd_byte_ens, // Main memory read enable
    mem_valid_in,// Valid pulse corresponding dmem inputs above
    1, // Always ready for output valid
    // Memory map inputs
    mem_map_inputs
  );
  o.mem_out_of_range = dmem_out.mem_out_of_range; // debug
  // Outputs from memory map
  o.mem_map_outputs = dmem_out.mem_map_outputs;
  // Transition out of MEM_START depends on ready output from memory
  if(state==MEM_START){
    if(dmem_out.ready_for_inputs){
      // All mem ops takes 1+ cycle, dont need same cycle transition
      next_state = MEM_END;
    }
  }
  // Data memory outputs
  if(state==MEM_END){
    printf("Waiting for MEM to finish...\n");
    if(dmem_out.valid){
      // Read output available from dmem_out
      if(decoded_reg.mem_rd_byte_ens[0]){
        printf("Read Mem[0x%X] = %d finished\n", mem_addr, dmem_out.rd_data);
      }
      if(decoded_reg.mem_wr_byte_ens[0]){
        printf("Write Mem[0x%X] finished\n", mem_addr);
      }
      state = WRITE_BACK_NEXT_PC; next_state = state; // SAME CYCLE STATE TRANSITION
    }
  }

  // Write Back + Next PC
  // default values needed for feedback signals
  reg_wr_en = 0; // default no writes 
  reg_wr_addr = 0;
  reg_wr_data = 0;
  if(state==WRITE_BACK_NEXT_PC){
    printf("Write Back + Next PC:\n");
    // Reg file write back, drive inputs (FEEDBACK)
    reg_wr_en = decoded_reg.reg_wr;
    reg_wr_addr = decoded_reg.dest;
    // Determine reg data to write back (sign extend etc)
    reg_wr_data = select_reg_wr_data(
      decoded_reg,
      exe, // Not _reg since might be shortcut from same cycle here from EXE_END
      dmem_out.rd_data,
      pc_plus4_reg
    );
    // Branch/Increment PC
    pc = select_next_pc(
     decoded_reg,
     exe, // Not _reg since might be shortcut from same cycle here from EXE_END
     pc_plus4_reg
    );
    next_state = FETCH_START;
  }

  // Debug override if ever signal errors, halt
  if(o.pc_out_of_range | o.mem_out_of_range | o.unknown_op){
    next_state = WTF;
  }
  // Hold in starting state during reset
  if(reset){
    next_state = FETCH_START;
    pc = 0;
  }

  // Reg update
  state = next_state;
  pc_plus4_reg = pc_plus4;
  imem_out_reg = imem_out;
  decoded_reg = decoded;
  reg_file_out_reg = reg_file_out;
  exe_reg = exe;
  mem_wr_byte_ens_reg = mem_wr_byte_ens;
  mem_rd_byte_ens_reg = mem_rd_byte_ens;
  mem_addr_reg = mem_addr;
  mem_wr_data_reg = mem_wr_data;
  mem_valid_in_reg = mem_valid_in;
  dmem_out_reg = dmem_out;

  return o;
}
