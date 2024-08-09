// RISCV CPU, FSM that takes multiple cycles
// uses autopipelines for some stages

#pragma PART "xc7a35ticsg324-1l" //LFE5U-85F-6BG381C"
#include "uintN_t.h"
#include "intN_t.h"
#include "stream/stream.h"
DECL_STREAM_TYPE(uint32_t)

// Include test gcc compiled program
#include "gcc_test/mem_map.h" 
#include "gcc_test/text_mem_init.h"
#include "gcc_test/data_mem_init.h"

// BRAM modules as needed by user memory mappings
#ifdef MMIO_BRAM0
#include "ram.h" 
DECL_4BYTE_RAM_SP_RF_1(
  bram0_ram,
  (MMIO_BRAM0_SIZE/4),
  MMIO_BRAM0_INIT
)
#endif

// AXI buses as needed by user memory mappings
#ifdef MMIO_AXI0
// Include code for Xilinx DDR AXI shared resource bus as frame buffer example
// Declares AXI shared resource bus wires
//   host_clk_to_dev(axi_xil_mem) and dev_to_host_clk(axi_xil_mem)
#define AXI_RAM_MODE_DDR // Configure frame buffer to use Xilinx AXI DDR RAM (not bram)
#include "examples/shared_resource_bus/axi_frame_buffer/dual_frame_buffer.c"
#endif

// I2S RX + TX code hard coded in loop back
// Configured to use memory mapped addr offset in CPU's AXI0 region
#include "examples/arty/src/i2s/i2s_axi_loopback.c"

// Helpers macros for building mmio modules
#include "mem_map.h" 
// Define MMIO inputs and outputs
typedef struct my_mmio_in_t{
  mm_status_regs_t status;
}my_mmio_in_t;
typedef struct my_mmio_out_t{
  mm_ctrl_regs_t ctrl;
}my_mmio_out_t;
// Define the hardware memory for those IO
// See typedefs for valid and ready handshake used on input and output
RISCV_DECL_MEM_MAP_MOD_OUT_T(my_mmio_out_t)
riscv_mem_map_mod_out_t(my_mmio_out_t) my_mem_map_module(
  RISCV_MEM_MAP_MOD_INPUTS(my_mmio_in_t)
){
  riscv_mem_map_mod_out_t(my_mmio_out_t) o;
  
  // Two states like CPU
  static uint1_t is_START_state = 1; // Otherwise is END
  // START, END: 
  //  same cycle for regs, 1 cycle delay for BRAM, variable wait for AXI RAMs etc

  // What kind of memory mapped storage?
  static uint1_t word_wr_en;
  static uint1_t word_rd_en;
  // 'is type' is register, set in START and held until end (based on addr only valid during input)
  // Signals and default values for storage types
  //  REGISTERS
  static uint1_t mm_type_is_regs; 
  uint1_t mm_regs_enabled; // Default no reg op
  //  BRAMS
  #ifdef MMIO_BRAM0
  static uint1_t mmio_type_is_bram0;
  uint32_t bram0_word_addr = (addr - MMIO_BRAM0_ADDR)>>2; // Account for offset in memory and 32b word addressing
  uint1_t bram0_valid_in; // Default no bram op
  #endif
  //  AXI RAMs // TODO MACROs to easily map multiple AXI buses? shared resource buses in general?
  #ifdef MMIO_AXI0
  static uint1_t mmio_type_is_axi0;
  uint32_t axi0_addr = addr - MMIO_AXI0_ADDR; // Account for offset in memory
  host_to_dev(axi_xil_mem, cpu) = axi_shared_bus_t_HOST_TO_DEV_NULL; // Default no mem op
  #endif

  // MM Control+status registers
  static mm_ctrl_regs_t ctrl;
  o.outputs.ctrl = ctrl; // output reg
  static mm_status_regs_t status;
  // MM Handshake regs start off looking like regular ctrl+status MM regs
  static mm_handshake_data_t handshake_data;
  static mm_handshake_valid_t handshake_valid;

  // Start MM operation
  if(is_START_state){
    // Wait for valid input start signal 
    if(valid){
      // Write or read helper flags
      word_wr_en = 0;
      word_rd_en = 0;
      uint32_t i;
      for(i=0;i<4;i+=1){
        word_wr_en |= wr_byte_ens[i];
        word_rd_en |= rd_byte_ens[i];
      }
      // Starting regs operation?
      mm_type_is_regs = (
        ( (addr>=MM_CTRL_REGS_ADDR)   & (addr<(MM_CTRL_REGS_ADDR+sizeof(mm_ctrl_regs_t))) ) |
        ( (addr>=MM_STATUS_REGS_ADDR) & (addr<(MM_STATUS_REGS_ADDR+sizeof(mm_status_regs_t))) ) |
        ( (addr>=MM_HANDSHAKE_DATA_ADDR) & (addr<(MM_HANDSHAKE_DATA_ADDR+sizeof(mm_handshake_data_t))) ) |
        ( (addr>=MM_HANDSHAKE_VALID_ADDR) & (addr<(MM_HANDSHAKE_VALID_ADDR+sizeof(mm_handshake_valid_t))) )
      );
      if(mm_type_is_regs){
        // Regs always ready now, i.e. if output was ready
        o.ready_for_inputs = ready_for_outputs;
        o.addr_is_mapped = 1;
        // Valid pulse to do reg op this cycle when ready
        mm_regs_enabled = o.ready_for_inputs;
      }
      // Starting BRAM operation?
      #ifdef MMIO_BRAM0
      mmio_type_is_bram0 = (addr>=MMIO_BRAM0_ADDR) & (addr<(MMIO_BRAM0_ADDR+MMIO_BRAM0_SIZE));
      if(mmio_type_is_bram0){
        // BRAM always ready now, i.e. if output was ready
        // (assumed will be ready one cycle later too for bram output)
        o.ready_for_inputs = ready_for_outputs;
        o.addr_is_mapped = 1;
        // Valid pulse into BRAM when ready
        bram0_valid_in = o.ready_for_inputs;
      }
      #endif
      // AXI0 start/request signaling (direct global wiring for now)
      #ifdef MMIO_AXI0
      // Use helper axi shared resource bus fsm funcs to do the AXI stuff and signal when done
      mmio_type_is_axi0 = (addr>=MMIO_AXI0_ADDR) & (addr<(MMIO_AXI0_ADDR+MMIO_AXI0_SIZE));
      if(mmio_type_is_axi0){
        // Start a write
        if(word_wr_en){
          // AXIS write addr + data setup
          axi_write_req_t axi_wr_req;
          axi_wr_req.awaddr = axi0_addr;
          axi_wr_req.awlen = 1-1; // size=1 minus 1: 1 transfer cycle (non-burst)
          axi_wr_req.awsize = 2; // 2^2=4 bytes per transfer
          axi_wr_req.awburst = BURST_FIXED; // Not a burst, single fixed address per transfer 
          axi_write_data_t axi_wr_data;
          //  Which of 4 bytes are being written?
          uint32_t i;
          for(i=0; i<4; i+=1)
          {
            axi_wr_data.wdata[i] = wr_data >> (i*8);
            axi_wr_data.wstrb[i] = wr_byte_ens[i];
          }
          // Invoke helper FSM
          axi_shared_bus_t_write_start_logic_outputs_t write_start =  
            axi_shared_bus_t_write_start_logic(
              axi_wr_req,
              axi_wr_data, 
              1,
              dev_to_host(axi_xil_mem, cpu).write
            ); 
          host_to_dev(axi_xil_mem, cpu).write = write_start.to_dev;
          // Finally ready and done with inputs when start finished
          if(write_start.done){ 
            o.ready_for_inputs = 1;
          }
        }
        // Start a read
        if(word_rd_en){
          // AXIS read setup
          axi_read_req_t axi_rd_req;
          axi_rd_req.araddr = axi0_addr;
          axi_rd_req.arlen = 1-1; // size=1 minus 1: 1 transfer cycle (non-burst)
          axi_rd_req.arsize = 2; // 2^2=4 bytes per transfer
          axi_rd_req.arburst = BURST_FIXED; // Not a burst, single fixed address per transfer
          // Invoke helper FSM
          axi_shared_bus_t_read_start_logic_outputs_t read_start =  
            axi_shared_bus_t_read_start_logic(
              axi_rd_req,
              1,
              dev_to_host(axi_xil_mem, cpu).read.req_ready
            ); 
          host_to_dev(axi_xil_mem, cpu).read.req = read_start.req;
          // Finally ready and done with inputs when start finished
          if(read_start.done){ 
            o.ready_for_inputs = 1;
          }
        }
      }
      #endif
      // Goto end state once ready for input
      if(o.ready_for_inputs){
        is_START_state = 0;
      }
    }
  }

  // Handshake valid signals are sometimes auto set/cleared
  mm_handshake_valid_t handshake_valid_reg_value = handshake_valid; // Before writes below

  // Memory muxing/select logic for control and status registers
  if(mm_regs_enabled){
    STRUCT_MM_ENTRY_NEW(MM_CTRL_REGS_ADDR, mm_ctrl_regs_t, ctrl, ctrl, addr, o.addr_is_mapped, o.rd_data)
    STRUCT_MM_ENTRY_NEW(MM_STATUS_REGS_ADDR, mm_status_regs_t, status, status, addr, o.addr_is_mapped, o.rd_data)
    STRUCT_MM_ENTRY_NEW(MM_HANDSHAKE_DATA_ADDR, mm_handshake_data_t, handshake_data, handshake_data, addr, o.addr_is_mapped, o.rd_data)
    STRUCT_MM_ENTRY_NEW(MM_HANDSHAKE_VALID_ADDR, mm_handshake_valid_t, handshake_valid, handshake_valid, addr, o.addr_is_mapped, o.rd_data)
  }

  #ifdef I2S_RX_MONITOR_PORT
  // Handshake data for cpu read written when ready got valid data
  uint1_t i2s_rx_out_desc_rd_en = ~handshake_valid_reg_value.i2s_rx_out_desc;
  i2s_rx_descriptors_monitor_fifo_read_t i2s_rx_out_desc_fifo =
     i2s_rx_descriptors_monitor_fifo_READ_1(i2s_rx_out_desc_rd_en);
  if(i2s_rx_out_desc_rd_en & i2s_rx_out_desc_fifo.valid){
    handshake_data.i2s_rx_out_desc = i2s_rx_out_desc_fifo.data[0];
    handshake_valid.i2s_rx_out_desc = 1;
  }
  #endif

  // BRAM0 instance
  #ifdef MMIO_BRAM0
  bram0_ram_out_t bram0_ram_out = bram0_ram(
    bram0_word_addr, wr_data, wr_byte_ens, bram0_valid_in
  );
  #endif


  // End MMIO operation
  if(~is_START_state){
    o.addr_is_mapped = 1;
    // Ending regs operation
    if(mm_type_is_regs){
      // No ready to connect since is same cycle op, known ready from earlier
      // Done in same cycle, get ready to start next cycle
      o.valid = 1;
      // rd_data and addr_is_mapped handled in STRUCT_MM helper macro
    }
    // End bram operation
    #ifdef MMIO_BRAM0
    if(mmio_type_is_bram0){
      // No ready to connect since is assumed ready if ready last cycle
      o.valid = bram0_ram_out.valid0;
      o.rd_data = bram0_ram_out.rd_data0;
    }
    #endif
    // End AXI0 operation
    #ifdef MMIO_AXI0
    #ifdef MMIO_AXI0_RAW_HAZZARD
    // Hazzard doesnt wait for writes to finish. Ignores/drains responses
    host_clk_to_dev(axi_xil_mem).write.resp_ready = 1;
    #endif
    if(mmio_type_is_axi0){
      #ifdef MMIO_AXI0_RAW_HAZZARD
      if(word_wr_en){
        // Hazzard dont wait for writes to finish (see ready=1 always above)
        o.valid = 1;
      }else{
        // Regular read wait for valid response
        host_clk_to_dev(axi_xil_mem).read.data_ready = ready_for_outputs;
        o.valid = dev_to_host_clk(axi_xil_mem).read.data.valid;
      }
      #else // Normal wait for mem to properly finish both reads or writes
      // Signal ready for both read and write responses
      // (only one in use)
      host_to_dev(axi_xil_mem, cpu).read.data_ready = ready_for_outputs;
      host_to_dev(axi_xil_mem, cpu).write.resp_ready = ready_for_outputs;
      // Either write or read resp is valid done signal
      o.valid = dev_to_host(axi_xil_mem, cpu).read.data.valid | 
                dev_to_host(axi_xil_mem, cpu).write.resp.valid;
      #endif
      // Read data is 4 bytes into u32
      o.rd_data = axi_read_to_data(dev_to_host(axi_xil_mem, cpu).read.data.burst.data_resp.user);
    }
    #endif
    // Start over when done
    if(o.valid & ready_for_outputs){
      is_START_state = 1;
    }
  }

  // Input regs
  status = inputs.status;

  return o;
}

// RISC-V components
// For now hard coded flags to enable different extensions
#define RV32_M
#define RISCV_REGFILE_1_CYCLE
#include "risc-v.h"

// Declare instruction and data memory
// also includes memory mapped IO
#define riscv_name fsm_riscv
#define RISCV_IMEM_INIT         text_MEM_INIT // from gcc_test/
#define RISCV_IMEM_SIZE_BYTES   IMEM_SIZE     // from gcc_test/
#define RISCV_DMEM_INIT         data_MEM_INIT // from gcc_test/
#define RISCV_DMEM_SIZE_BYTES   DMEM_SIZE     // from gcc_test/
#define riscv_mem_map           my_mem_map_module
#define riscv_mem_map_inputs_t  my_mmio_in_t
#define riscv_mem_map_outputs_t my_mmio_out_t
#define RISCV_IMEM_1_CYCLE
#define RISCV_DMEM_1_CYCLE
// Multi cycle is not a pipeline
#define RISCV_IMEM_NO_AUTOPIPELINE
#define RISCV_DMEM_NO_AUTOPIPELINE
#include "mem_decl.h"

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
  //     \/ SAME CYCLE \/
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

  // Decode
  if(state==FETCH_END_DECODE_REG_RD_START){
    printf("Decode:\n");
    // Decode the instruction to control signals
    printf("Instruction: 0x%X\n", imem_out.rd_data1);
    decoded = decode(imem_out.rd_data1);
    o.unknown_op = decoded.unknown_op; // debug
    next_state = REG_RD_END_EXE_START;
  }

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
      // MMIO regs can read in same cycle, if bad for fmax can make 1 cycle delay like bram...
      state = MEM_END; next_state = state; // SAME CYCLE STATE TRANSITION
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
  if(o.mem_out_of_range | o.unknown_op){
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

// LEDs for demo
#include "leds/leds_port.c"
// CDC for reset
#include "cdc.h"

MAIN_MHZ(cpu_top, 6.25) // 6.25 testing with div ops but dont wait for pipelining
void cpu_top(uint1_t areset)
{
  // TODO drive or dont use reset during sim
  // Sync reset
  uint1_t reset = xil_cdc2_bit(areset);
  //uint1_t reset = 0;

  // Instance of core
  my_mmio_in_t in;
  in.status.button = 0; // TODO
  #ifdef I2S_RX_MONITOR_PORT
  in.status.i2s_rx_out_desc_overflow = xil_cdc2_bit(i2s_rx_descriptors_out_monitor_overflow); // CDC since async
  #endif
  riscv_out_t out = fsm_riscv(reset, in);

  // Sim debug
  //unknown_op = out.unknown_op;
  //mem_out_of_range = out.mem_out_of_range;
  //halt = out.mem_map_outputs.halt;
  //main_return = out.mem_map_outputs.return_value;

  // Output LEDs for hardware debug
  static uint1_t mem_out_of_range_reg;
  static uint1_t unknown_op_reg;
  leds = 0;
  leds |= (uint4_t)out.mem_map_outputs.ctrl.led << 0;
  leds |= (uint4_t)mem_out_of_range_reg << 1;
  leds |= (uint4_t)unknown_op_reg << 2;

  // Sticky on so human can see single cycle pulse
  mem_out_of_range_reg |= out.mem_out_of_range;
  unknown_op_reg |= out.unknown_op;
  if(reset){
    mem_out_of_range_reg = 0;
    unknown_op_reg = 0;
  }
}

