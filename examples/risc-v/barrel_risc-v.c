//barrel_risc-v.c
// START OFF AS COPY OF SINGLE CYCLE CPU rewritten ~netlist/multi MAIN graph style
// For now has no flow control
// Main memory is a LUTRAM pipeline that is always flowing
// Need more ports since feedback to mems?
#pragma PART "xc7a35ticsg324-1l"

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

// Interconnect wires
#define N_THREADS 1 // TODO 4
typedef struct thread_context_t{
  uint1_t thread_id;
  uint1_t thread_valid;
  uint32_t pc;
  uint32_t next_pc;
  uint32_t instruction;
  decoded_t decoded;
  reg_file_out_t reg_file_rd_datas;
  execute_t exe;
  uint32_t mem_rd_data;
}thread_context_t;
thread_context_t pc_to_imem;
thread_context_t imem_to_decode;
thread_context_t decode_to_reg_rd;
thread_context_t reg_rd_to_exe;
thread_context_t exe_to_dmem;
thread_context_t dmem_to_reg_wr;
thread_context_t reg_wr_to_branch;
thread_context_t branch_to_pc;
// Per thread IO
uint1_t mem_out_of_range[N_THREADS]; // Exception, stop sim
uint1_t unknown_op[N_THREADS]; // Exception, stop sim
riscv_mem_map_inputs_t  mem_map_inputs[N_THREADS];
riscv_mem_map_outputs_t mem_map_outputs[N_THREADS];


// Current PC reg + thread ID + valid bit
// TODO how to stop and start threads?
#pragma MAIN pc_thread_start_top
void pc_thread_start_top(){
  // Stage thread context, input from prev stage
  thread_context_t inputs = branch_to_pc;
  thread_context_t outputs = inputs;
  //
  static uint32_t pc_reg;
  static uint8_t thread_id_reg;
  static uint1_t thread_valid_reg = 1;
  outputs.pc = pc_reg;
  outputs.thread_id = thread_id_reg;
  outputs.thread_valid = thread_valid_reg;
  if(outputs.thread_valid)
  {
    printf("Thread %d: PC = 0x%X\n", outputs.thread_id, outputs.pc);
  }
  // TODO logic to update thread id+valid
  pc_reg = inputs.next_pc;
  //
  // Output to next stage
  pc_to_imem = outputs;
}


// Main memory  instance
// IMEM, 1 rd port
// DMEM, 1 RW port
//  Data memory signals are not driven until later
//  but are used now, requiring FEEDBACK pragma
//  + memory mapped IO signals
#pragma MAIN mem_stages
void mem_stages()
{
  // Stage thread context, input from prev stages
  thread_context_t imem_inputs = pc_to_imem;
  thread_context_t imem_outputs = imem_inputs;
  thread_context_t dmem_inputs = exe_to_dmem;
  thread_context_t dmem_outputs = dmem_inputs;
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

  // Output to next stage
  imem_to_decode = imem_outputs;
  dmem_to_reg_wr = dmem_outputs;
}
#ifdef riscv_mem_map_outputs_t
#ifdef riscv_mem_map_inputs_t
// LEDs for demo
#include "leds/leds_port.c"
#define CPU_CLK_MHZ 25.0
MAIN_MHZ(mm_io_connections, CPU_CLK_MHZ)
void mm_io_connections()
{
  // Output LEDs for hardware debug
  leds = 0;
  uint8_t tid;
  for(tid = 0; tid < N_THREADS; tid+=1)
  {
    mem_map_inputs[tid].core_id = tid;
    leds |= (uint4_t)mem_map_outputs[tid].led << tid;
  }
}
#endif
#endif


#pragma MAIN decode_stages
void decode_stages()
{
  // Stage thread context, input from prev stage
  thread_context_t inputs = imem_to_decode;
  thread_context_t outputs = inputs;
  //
  printf("Thread %d: Instruction: 0x%X\n", inputs.thread_id, inputs.instruction);
  outputs.decoded = decode(inputs.instruction);
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
  decode_to_reg_rd = outputs;
}


#pragma MAIN reg_file_stages
void reg_file_stages()
{
  // Stage thread context, input from prev stages
  thread_context_t reg_rd_inputs = decode_to_reg_rd;
  thread_context_t reg_rd_outputs = reg_rd_inputs;
  thread_context_t reg_wr_inputs = dmem_to_reg_wr;
  thread_context_t reg_wr_outputs = reg_wr_inputs;
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

  // Output to next stage
  reg_rd_to_exe = reg_rd_outputs;
  reg_wr_to_branch = reg_wr_outputs;
}


#pragma MAIN execute_stages
void execute_stages()
{
  // Stage thread context, input from prev stage
  thread_context_t inputs = reg_rd_to_exe;
  thread_context_t outputs = inputs;
  // 
  // Execute stage
  printf("Thread %d: Execute stage...\n", inputs.thread_id);
  uint32_t pc_plus4 = inputs.pc + 4;
  outputs.exe = execute(
    inputs.pc, pc_plus4, 
    inputs.decoded, 
    inputs.reg_file_rd_datas.rd_data1, inputs.reg_file_rd_datas.rd_data2
  );
  // Output to next stage
  exe_to_dmem = outputs;
}


// Calculate the next PC
// and depending on selected thread update PC regs
/*uint32_t pc_buffer(uint32_t next_pc, uint1_t wr_en){
  static uint32_t pc_reg;
  uint32_t rv  = pc_reg;
  if(wr_en){
    pc_reg = next_pc;
  }
  return rv;
}*/
#pragma MAIN branch_next_pc_stages
void branch_next_pc_stages()
{
  // Stage thread context, input from prev stage
  thread_context_t inputs = reg_wr_to_branch;
  thread_context_t outputs = inputs;
  //
  uint32_t pc_plus4 = inputs.pc + 4;
  uint8_t tid = 0;
  outputs.next_pc = 0;
  //uint32_t pcs[N_THREADS];
  //uint32_t next_pcs[N_THREADS];
  //for(tid = 0; tid < N_THREADS; tid+=1)
  //{
    uint1_t thread_sel = inputs.thread_valid & (inputs.thread_id==tid);
    if(thread_sel){
      // Branch/Increment PC
      if(inputs.decoded.exe_to_pc){
        printf("Thread %d: Next PC: Execute Result = 0x%X...\n", tid, inputs.exe.result);
        //next_pcs[tid] = exe.result;
        outputs.next_pc = inputs.exe.result;
      }else{
        // Default next pc
        printf("Thread %d: Next PC: Default = 0x%X...\n", tid, pc_plus4);
        //next_pcs[tid] = pc_plus4;
        outputs.next_pc = pc_plus4;
      }
    }
    //pcs[tid] = pc_buffer(next_pcs[i], thread_sel);
  //}
  // Mux select next PC based on thread id
  //next_pc = next_pcs[thread_id];

  // Output to next stage
  branch_to_pc = outputs;
}
