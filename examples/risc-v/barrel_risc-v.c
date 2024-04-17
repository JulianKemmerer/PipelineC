// Copy or single cycle CPU rewritten ~netlist/multi MAIN graph style
// For now has no flow control
// TODO make multi instances of this barrel

// Need more ports since feedback to mems?
#pragma PART "xc7a100tcsg324-1"

// RISC-V components
#include "risc-v.h"

// Include test gcc compiled program
#include "gcc_test/mem_init.h" // MEM_INIT,MEM_INIT_SIZE

// Declare memory map information
// Starts with shared with software memory map info
#include "gcc_test/mem_map.h" 
// Define inputs and outputs
typedef struct my_mmio_in_t{
  uint8_t core_id;
}my_mmio_in_t;
typedef struct my_mmio_out_t{
  uint32_t return_value;
  uint1_t halt;
  uint1_t led;
}my_mmio_out_t;
// Define the hardware memory for those IO
RISCV_DECL_MEM_MAP_MOD_OUT_T(my_mmio_out_t)
riscv_mem_map_mod_out_t(my_mmio_out_t) my_mem_map_module(
  RISCV_MEM_MAP_MOD_INPUTS(my_mmio_in_t)
){
  // Outputs
  static riscv_mem_map_mod_out_t(my_mmio_out_t) o;
  o.addr_is_mapped = 0; // since o is static regs
  // Memory muxing/select logic
  // Uses helper comparing word address and driving a variable
  o.outputs.return_value = inputs.core_id; // Override typical reg read behavior
  WORD_MM_ENTRY(o, CORE_ID_RETURN_OUTPUT_ADDR, o.outputs.return_value)
  o.outputs.halt = wr_byte_ens[0] & (addr==CORE_ID_RETURN_OUTPUT_ADDR);
  WORD_MM_ENTRY(o, LED_ADDR, o.outputs.led)
  return o;
}

// Declare a combined instruction and data memory
// also includes memory mapped IO
#define riscv_name              my_riscv
#define RISCV_MEM_INIT          MEM_INIT // from gcc_test
#define RISCV_MEM_SIZE_BYTES    MEM_INIT_SIZE // from gcc_test
#define riscv_mem_map           my_mem_map_module
#define riscv_mem_map_inputs_t  my_mmio_in_t
#define riscv_mem_map_outputs_t my_mmio_out_t
// Support old single core using mem_map_out_t
#include "mem_map.h"
#ifdef riscv_mem_map_outputs_t
#define riscv_mmio_mod_out_t riscv_mem_map_mod_out_t(riscv_mem_map_outputs_t)
#else
#define riscv_mmio_mod_out_t mem_map_out_t
#endif
#include "mem_decl.h" // declare my_riscv_mem_out my_riscv_mem() func

// Config threads
// Mhz               | ~40  ~55 150  160  ...~fmax 400Mhz?
// Threads(~#stages) | 1    3   9    16      64?
// LIMITING FACTOR IS LUTRAM
// CONVERT TO BRAM
// THEN LIMITING FACTOR BRAM
// At ~max~64 threads how much BRAM is used?
//   How many copies of the ~max~64 thread single barrel could exist?
//  MULTI BARRELS!
#define CPU_CLK_MHZ 50.0
#define N_THREADS 3
// Interconnect wires between stages
typedef struct thread_context_t{
  uint8_t thread_id;
  uint1_t thread_valid;
  uint32_t pc;
  uint32_t next_pc;
  uint32_t instruction;
  decoded_t decoded;
  reg_file_out_t reg_file_rd_datas;
  execute_t exe;
  uint32_t mem_rd_data;
}thread_context_t;
thread_context_t pc_inputs;
thread_context_t pc_outputs;
thread_context_t imem_inputs;
thread_context_t imem_outputs;
thread_context_t decode_inputs;
thread_context_t decode_outputs;
thread_context_t reg_rd_inputs;
thread_context_t reg_rd_outputs;
thread_context_t exe_inputs;
thread_context_t exe_outputs;
thread_context_t dmem_inputs;
thread_context_t dmem_outputs;
thread_context_t reg_wr_inputs;
thread_context_t reg_wr_outputs;
thread_context_t branch_inputs;
thread_context_t branch_outputs;
#pragma MAIN inter_stage_connections
#pragma FUNC_WIRES inter_stage_connections
void inter_stage_connections(){
  // Each inter stage connection is configurable
  // PC stage is 1 cycle delay +
  // All 8 interconnect delay regs
  // = baseline 9 threads from handpipelining alone
  #ifdef pc_to_imem_REG
  static thread_context_t pc_to_imem;
  imem_inputs = pc_to_imem;
  pc_to_imem = pc_outputs;
  #else
  imem_inputs = pc_outputs;
  #endif
  #ifdef imem_to_decode_REG
  static thread_context_t imem_to_decode;
  decode_inputs = imem_to_decode;
  imem_to_decode = imem_outputs;
  #else
  decode_inputs = imem_outputs;
  #endif
  #ifdef decode_to_reg_rd_REG
  static thread_context_t decode_to_reg_rd;
  reg_rd_inputs = decode_to_reg_rd;
  decode_to_reg_rd = decode_outputs;
  #else
  reg_rd_inputs = decode_outputs;
  #endif
  #ifdef reg_rd_to_exe_REG
  static thread_context_t reg_rd_to_exe;
  exe_inputs = reg_rd_to_exe;
  reg_rd_to_exe = reg_rd_outputs;
  #else
  exe_inputs = reg_rd_outputs;
  #endif
  #ifdef exe_to_dmem_REG
  static thread_context_t exe_to_dmem;
  dmem_inputs = exe_to_dmem;
  exe_to_dmem = exe_outputs;
  #else
  dmem_inputs = exe_outputs;
  #endif
  #ifdef dmem_to_reg_wr_REG
  static thread_context_t dmem_to_reg_wr;
  reg_wr_inputs = dmem_to_reg_wr;
  dmem_to_reg_wr = dmem_outputs;
  #else
   reg_wr_inputs = dmem_outputs;
  #endif
  #ifdef reg_wr_to_branch_REG
  static thread_context_t reg_wr_to_branch;
  branch_inputs = reg_wr_to_branch;
  reg_wr_to_branch = reg_wr_outputs;
  #else
  branch_inputs = reg_wr_outputs;
  #endif
  #ifdef branch_to_pc_REG
  static thread_context_t branch_to_pc;
  pc_inputs = branch_to_pc;
  branch_to_pc = branch_outputs;
  #else
  pc_inputs = branch_outputs;
  #endif
}
// Per thread IO
uint1_t mem_out_of_range[N_THREADS]; // Exception, stop sim
uint1_t unknown_op[N_THREADS]; // Exception, stop sim
riscv_mem_map_inputs_t  mem_map_inputs[N_THREADS];
riscv_mem_map_outputs_t mem_map_outputs[N_THREADS];


// Temp control fsm trying to start up to max threads
uint1_t barrel_start_ready;
uint32_t barrel_start_pc;
uint8_t barrel_start_thread_id;
uint1_t barrel_start_valid;
#pragma MAIN thread_starter_fsm
void thread_starter_fsm(){
  static uint8_t running_threads;
  barrel_start_valid = running_threads < N_THREADS;
  barrel_start_thread_id = running_threads;
  barrel_start_pc = 0;
  if(barrel_start_ready){
    printf("Thread %d: Started!\n", barrel_start_thread_id);
    running_threads += 1;
  }
}


// Current PC reg + thread ID + valid bit
// TODO how to stop and start threads?
#pragma MAIN pc_thread_start_stage
#pragma FUNC_LATENCY pc_thread_start_stage 1
void pc_thread_start_stage(){
  // Stage thread context, input from prev stage
  thread_context_t inputs = pc_inputs;
  // PC is start of pipelined and does not ned to pass through outputs to inputs
  thread_context_t outputs;
  //
  // These regs give this pc stage 1 cycle of delay as baseline (not comb pass through)
  static uint32_t pc_reg;
  static uint8_t thread_id_reg;
  static uint1_t thread_valid_reg;
  outputs.pc = pc_reg;
  outputs.thread_id = thread_id_reg;
  outputs.thread_valid = thread_valid_reg;
  if(outputs.thread_valid)
  {
    printf("Thread %d: PC = 0x%X\n", outputs.thread_id, outputs.pc);
  }
  pc_reg = 0;
  thread_id_reg = 0;
  thread_valid_reg = 0;
  barrel_start_ready = 0;
  if(inputs.thread_valid){
    pc_reg = inputs.next_pc;
    thread_id_reg = inputs.thread_id;
    thread_valid_reg = 1;
  }else{
    // No next thread input to stage, accept stage
    barrel_start_ready = 1;
    if(barrel_start_valid){
      pc_reg = barrel_start_pc;
      thread_id_reg = barrel_start_thread_id;
      thread_valid_reg = 1;
    }
  }
  //
  // Output to next stage
  pc_outputs = outputs;
}


// Main memory  instance
// IMEM, 1 rd port
// DMEM, 1 RW port
//  Data memory signals are not driven until later
//  but are used now, requiring FEEDBACK pragma
//  + memory mapped IO signals
#pragma MAIN mem_2_stages
void mem_2_stages()
{
  // Stage thread context, input from prev stages
  imem_outputs = imem_inputs;
  dmem_outputs = dmem_inputs;
  //
  // Each thread has own instances of a shared instruction and data memory
  uint8_t tid;
  // Only current thread mem is enabled
  // Output from multiple threads is muxed
  uint32_t instructions[N_THREADS];
  uint32_t mem_rd_datas[N_THREADS];
  for(tid = 0; tid < N_THREADS; tid+=1)
  {
    uint32_t mem_addr;
    uint32_t mem_wr_data;
    uint1_t mem_wr_byte_ens[4];
    uint1_t mem_rd_en;
    mem_addr = dmem_inputs.exe.result; // addr always from execute module, not always used
    mem_wr_data = dmem_inputs.reg_file_rd_datas.rd_data2;
    mem_wr_byte_ens = dmem_inputs.decoded.mem_wr_byte_ens;
    mem_rd_en = dmem_inputs.decoded.mem_rd;

    // gate enables with thread id compare and valid
    if(!(dmem_inputs.thread_valid & (dmem_inputs.thread_id==tid))){
      mem_wr_byte_ens[0] = 0;
      mem_wr_byte_ens[1] = 0;
      mem_wr_byte_ens[2] = 0;
      mem_wr_byte_ens[3] = 0;
      mem_rd_en = 0;
    }

    if(mem_wr_byte_ens[0]){
      printf("Thread %d: Write Mem[0x%X] = %d\n", tid, mem_addr, mem_wr_data);
    }
    my_riscv_mem_out_t mem_out = my_riscv_mem(
      imem_inputs.pc>>2, // Instruction word read address based on PC
      mem_addr, // Main memory read/write address
      mem_wr_data, // Main memory write data
      mem_wr_byte_ens, // Main memory write data byte enables
      mem_rd_en // Main memory read enable
      // Optional memory map inputs
      #ifdef riscv_mem_map_inputs_t
      , mem_map_inputs[tid]
      #endif
    );
    instructions[tid] = mem_out.inst;
    mem_rd_datas[tid] = mem_out.rd_data;
    if(mem_rd_en){
      printf("Thread %d: Read Mem[0x%X] = %d\n", tid, mem_addr, mem_out.rd_data);
    }
    mem_out_of_range[tid] = mem_out.mem_out_of_range;
    mem_map_outputs[tid] = mem_out.mem_map_outputs;
  }
  // Mux output based on current thread
  imem_outputs.instruction = instructions[imem_inputs.thread_id];
  dmem_outputs.mem_rd_data = mem_rd_datas[dmem_inputs.thread_id];
}
#ifdef riscv_mem_map_outputs_t
#ifdef riscv_mem_map_inputs_t
// LEDs for demo
#include "leds/leds_port.c"
MAIN_MHZ(mm_io_connections, CPU_CLK_MHZ)
#pragma FUNC_WIRES mm_io_connections
void mm_io_connections()
{
  // Output LEDs for hardware debug
  leds = 0;

  // temp dumb AND together
  uint1_t led = 1;
  uint8_t tid;
  for(tid = 0; tid < N_THREADS; tid+=1)
  {
    mem_map_inputs[tid].core_id = tid;
    led &= mem_map_outputs[tid].led;
    //leds |= (uint4_t)mem_map_outputs[tid].led << tid;
  }
  leds = led;
}
#endif
#endif


#pragma MAIN decode_stages
void decode_stages()
{
  // Stage thread context, input from prev stage
  thread_context_t inputs = decode_inputs;
  thread_context_t outputs = inputs;
  //
  if(inputs.thread_valid){
    printf("Thread %d: Instruction: 0x%X\n", inputs.thread_id, inputs.instruction);
    outputs.decoded = decode(inputs.instruction);
  }
  // Multiple unknown op outputs per thread
  uint8_t tid;
  for(tid = 0; tid < N_THREADS; tid+=1)
  {
    unknown_op[tid] = 0;
    if(inputs.thread_valid & (inputs.thread_id==tid)){
      unknown_op[tid] = outputs.decoded.unknown_op;
    }
  }
  // Output to next stage
  decode_outputs = outputs;
}


#pragma MAIN reg_file_2_stages
void reg_file_2_stages()
{
  // Stage thread context, input from prev stages
  reg_rd_outputs = reg_rd_inputs;
  reg_wr_outputs = reg_wr_inputs;
  // 
  // Each thread has own instances of a shared instruction and data memory
  uint8_t tid;
  // Only current thread mem is enabled
  // Output from multiple threads is muxed
  reg_file_out_t reg_file_rd_datas[N_THREADS];
  for(tid = 0; tid < N_THREADS; tid+=1)
  {
    uint1_t wr_thread_sel = reg_wr_inputs.thread_valid & (reg_wr_inputs.thread_id==tid);
    // Register file reads and writes
    uint5_t reg_wr_addr;
    uint32_t reg_wr_data;
    uint1_t reg_wr_en;
    if(wr_thread_sel){
      // Reg file write back, drive inputs 
      reg_wr_en = reg_wr_inputs.decoded.reg_wr;
      reg_wr_addr = reg_wr_inputs.decoded.dest;
      reg_wr_data = reg_wr_inputs.exe.result;
      // Determine data to write back
      if(reg_wr_inputs.decoded.mem_to_reg){
        printf("Thread %d: Write RegFile: MemRd->Reg...\n", tid);
        reg_wr_data = reg_wr_inputs.mem_rd_data;
      }else if(reg_wr_inputs.decoded.pc_plus4_to_reg){
        printf("Thread %d: Write RegFile: PC+4->Reg...\n", tid);
        reg_wr_data = reg_wr_inputs.pc + 4;
      }else{
        if(reg_wr_en)
          printf("Thread %d: Write RegFile: Execute Result->Reg...\n", tid);
      }
      if(reg_wr_en){
        printf("Thread %d: Write RegFile[%d] = %d\n", tid, reg_wr_inputs.decoded.dest, reg_wr_data);
      }
    }
    reg_file_rd_datas[tid] = reg_file(
      reg_rd_inputs.decoded.src1, // First read port address
      reg_rd_inputs.decoded.src2, // Second read port address
      reg_wr_addr, // Write port address
      reg_wr_data, // Write port data
      reg_wr_en // Write enable
    );
    // Reg read
    uint1_t rd_thread_sel = reg_rd_inputs.thread_valid & (reg_rd_inputs.thread_id==tid);
    if(rd_thread_sel){
      if(reg_rd_inputs.decoded.print_rs1_read){
        printf("Thread %d: Read RegFile[%d] = %d\n", tid, reg_rd_inputs.decoded.src1, reg_file_rd_datas[tid].rd_data1);
      }
      if(reg_rd_inputs.decoded.print_rs2_read){
        printf("Thread %d: Read RegFile[%d] = %d\n", tid, reg_rd_inputs.decoded.src2, reg_file_rd_datas[tid].rd_data2);
      }
    }
  }
  // Mux output for selected thread
  reg_rd_outputs.reg_file_rd_datas = reg_file_rd_datas[reg_rd_inputs.thread_id];
}


#pragma MAIN execute_stages
void execute_stages()
{
  // Stage thread context, input from prev stage
  thread_context_t inputs = exe_inputs;
  thread_context_t outputs = inputs; 
  // Execute stage
  uint32_t pc_plus4 = inputs.pc + 4;
  if(inputs.thread_valid){
    printf("Thread %d: Execute stage...\n", inputs.thread_id);
    outputs.exe = execute(
      inputs.pc, pc_plus4, 
      inputs.decoded, 
      inputs.reg_file_rd_datas.rd_data1, inputs.reg_file_rd_datas.rd_data2
    );
  }
  // Output to next stage
  exe_outputs = outputs;
}


// Calculate the next PC
#pragma MAIN branch_next_pc_stages
void branch_next_pc_stages()
{
  // Stage thread context, input from prev stage
  thread_context_t inputs = branch_inputs;
  thread_context_t outputs = inputs;
  //
  outputs.next_pc = 0;
  if(inputs.thread_valid){
    // Branch/Increment PC
    if(inputs.decoded.exe_to_pc){
      printf("Thread %d: Next PC: Execute Result = 0x%X...\n", inputs.thread_id, inputs.exe.result);
      //next_pcs[tid] = exe.result;
      outputs.next_pc = inputs.exe.result;
    }else{
      // Default next pc
      uint32_t pc_plus4 = inputs.pc + 4;
      printf("Thread %d: Next PC: Default = 0x%X...\n", inputs.thread_id, pc_plus4);
      outputs.next_pc = pc_plus4;
    }
  }
  // Output to next stage
  branch_outputs = outputs;
}
