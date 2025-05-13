// Instruction and data memory, used with risc-v_decl.h
#include "uintN_t.h"
#include "intN_t.h"
#include "compiler.h"
#include "arrays.h"
#include "ram.h"
#include "mem_map.h"

// Helper macro to rename wrapped user type
#ifndef riscv_mmio_mod_out_t
#define riscv_mmio_mod_out_t riscv_mem_map_mod_out_t(riscv_mem_map_outputs_t)
#endif

// Instruction and data memory initialized from gcc compile

// RAM with one read port for instructions
// Not using "ram.h" macros since is dumb single port
// and not using built in RAM_SF_RF_0 
// since dont want two ways of initializing RAM (C arrays, vs VHDL init string)
#define RISCV_IMEM_NUM_WORDS (RISCV_IMEM_SIZE_BYTES/4)
#define riscv_imem_ram_out_t PPCAT(riscv_name,_imem_ram_out_t)
typedef struct riscv_imem_ram_out_t
{
  uint32_t addr1;
  uint32_t rd_data1;
  uint1_t valid1;
}riscv_imem_ram_out_t;
#ifdef RISCV_IMEM_0_CYCLE
// Same cycle reads version
#define riscv_imem_ram PPCAT(riscv_name,_imem_ram_same_cycle)
riscv_imem_ram_out_t riscv_imem_ram(
  uint32_t addr1,
  uint1_t valid1
){
  __vhdl__("\n\
  constant SIZE : integer := " xstr(RISCV_IMEM_NUM_WORDS) "; \n\
  type ram_t is array(0 to SIZE-1) of unsigned(31 downto 0); \n\
  signal the_ram : ram_t := " RISCV_IMEM_INIT "; \n\
  -- Limit zero latency comb. read addr range to SIZE \n\
  -- since invalid addresses can occur as logic propogates \n\
  -- (this includes out of int32 range u32 values) \n\
  signal addr1_s : integer range 0 to SIZE-1 := 0; \n\
begin \n\
  process(all) begin \n\
    addr1_s <= to_integer(addr1(30 downto 0)) \n\
    -- synthesis translate_off \n\
    mod SIZE \n\
    -- synthesis translate_on \n\
    ; \n\
  end process; \n\
  return_output.addr1 <= addr1; \n\
  return_output.rd_data1 <= the_ram(addr1_s); \n\
  return_output.valid1 <= valid1; \n\
");
}
#endif
#ifdef RISCV_IMEM_1_CYCLE
// One cycle reads version
#define riscv_imem_ram PPCAT(riscv_name,_imem_ram_one_cycle)
#ifndef RISCV_IMEM_NO_AUTOPIPELINE
PRAGMA_MESSAGE(FUNC_LATENCY riscv_imem_ram 1)
#endif
riscv_imem_ram_out_t riscv_imem_ram(
  uint32_t addr1,
  uint1_t valid1
){
  __vhdl__("\n\
  constant SIZE : integer := " xstr(RISCV_IMEM_NUM_WORDS) "; \n\
  type ram_t is array(0 to SIZE-1) of unsigned(31 downto 0); \n\
  signal the_ram : ram_t := " RISCV_IMEM_INIT "; \n\
  -- Limit zero latency comb. read addr range to SIZE \n\
  -- since invalid addresses can occur as logic propogates \n\
  -- (this includes out of int32 range u32 values) \n\
  signal addr1_s : integer range 0 to SIZE-1 := 0; \n\
begin \n\
  process(all) begin \n\
    addr1_s <= to_integer(addr1(30 downto 0)) \n\
    -- synthesis translate_off \n\
    mod SIZE \n\
    -- synthesis translate_on \n\
    ; \n\
  end process; \n\
  process(clk) is \n\
  begin \n\
    if rising_edge(clk) then \n\
      if CLOCK_ENABLE(0)='1' then \n\
        return_output.addr1 <= addr1; \n\
        return_output.rd_data1 <= the_ram(addr1_s); \n\
        return_output.valid1 <= valid1; \n\
      end if; \n\
    end if; \n\
  end process; \n\
");
}
#endif


// Need a RAM with one r/w port for data mem
// Need byte enables needed for RISC-V SH and SB
#define RISCV_DMEM_NUM_WORDS (RISCV_DMEM_SIZE_BYTES/4)
#define riscv_dmem_ram_out_t PPCAT(riscv_name,_dmem_ram_out_t)
typedef struct riscv_dmem_ram_out_t
{
  uint32_t addr0;
  uint32_t wr_data0; uint1_t wr_byte_ens0[4];
  uint32_t rd_data0;
  uint1_t valid0;
}riscv_dmem_ram_out_t;
#ifdef RISCV_DMEM_0_CYCLE
// Same cycle reads version
#define riscv_dmem_ram PPCAT(riscv_name,_dmem_ram_same_cycle)
riscv_dmem_ram_out_t riscv_dmem_ram(
  uint32_t addr0,
  uint32_t wr_data0, uint1_t wr_byte_ens0[4],
  uint1_t valid0
){
  __vhdl__("\n\
  constant SIZE : integer := " xstr(RISCV_DMEM_NUM_WORDS) "; \n\
  type ram_t is array(0 to SIZE-1) of unsigned(31 downto 0); \n\
  signal the_ram : ram_t := " RISCV_DMEM_INIT "; \n\
  -- Limit zero latency comb. read addr range to SIZE \n\
  -- since invalid addresses can occur as logic propogates \n\
  -- (this includes out of int32 range u32 values) \n\
  signal addr0_s : integer range 0 to SIZE-1 := 0; \n\
begin \n\
  process(all) begin \n\
    addr0_s <= to_integer(addr0(30 downto 0)) \n\
    -- synthesis translate_off \n\
    mod SIZE \n\
    -- synthesis translate_on \n\
    ; \n\
  end process; \n\
  process(clk) is \n\
  begin \n\
    if rising_edge(clk) then \n\
      if CLOCK_ENABLE(0)='1' then \n\
        if valid0(0)='1' then \n\
          if wr_byte_ens0(0)(0)='1'then \n\
            the_ram(addr0_s)(7 downto 0) <= wr_data0(7 downto 0); \n\
          end if;  \n\
          if wr_byte_ens0(1)(0)='1'then \n\
            the_ram(addr0_s)(15 downto 8) <= wr_data0(15 downto 8); \n\
          end if;  \n\
          if wr_byte_ens0(2)(0)='1'then \n\
            the_ram(addr0_s)(23 downto 16) <= wr_data0(23 downto 16); \n\
          end if;  \n\
          if wr_byte_ens0(3)(0)='1'then \n\
            the_ram(addr0_s)(31 downto 24) <= wr_data0(31 downto 24); \n\
          end if;  \n\
        end if; \n\
      end if; \n\
    end if; \n\
  end process; \n\
  return_output.addr0 <= addr0; \n\
  return_output.rd_data0 <= the_ram(addr0_s); \n\
  return_output.wr_data0 <= wr_data0; \n\
  return_output.wr_byte_ens0 <= wr_byte_ens0; \n\
  return_output.valid0 <= valid0; \n\
");
}
#endif
#ifdef RISCV_DMEM_1_CYCLE
// One cycle reads version
#define riscv_dmem_ram PPCAT(riscv_name,_dmem_ram_one_cycle)
#ifndef RISCV_DMEM_NO_AUTOPIPELINE
PRAGMA_MESSAGE(FUNC_LATENCY riscv_dmem_ram 1)
#endif
// Single port, 1 clock latency, with byte enables like for CPU
// from ram.h
DECL_4BYTE_RAM_SP_RF_1(
  riscv_dmem_ram,
  RISCV_DMEM_NUM_WORDS,
  RISCV_DMEM_INIT
)
#endif

// Wrap data memory RAM with logic for memory map and unaligned access
#define riscv_dmem_out_t PPCAT(riscv_name,_dmem_out_t)
typedef struct riscv_dmem_out_t
{
  uint32_t rd_data;
  uint1_t valid; // done aka rd_data valid
  uint1_t ready_for_inputs;
  uint1_t mem_out_of_range; // Exception, stop sim
  #ifdef riscv_mem_map_outputs_t
  riscv_mem_map_outputs_t mem_map_outputs;
  #endif
}riscv_dmem_out_t;
#define riscv_dmem PPCAT(riscv_name,_dmem)

#ifndef RISCV_DMEM_NO_AUTOPIPELINE
riscv_dmem_out_t riscv_dmem(
  uint32_t rw_addr,
  uint32_t wr_data,
  uint1_t wr_byte_ens[4],
  uint1_t rd_byte_ens[4],
  uint1_t valid // aka start
  #ifdef riscv_mem_map_inputs_t
  , riscv_mem_map_inputs_t mem_map_inputs
  #endif
){
  riscv_dmem_out_t mem_out;

  // Write or read helper flags
  uint1_t word_wr_en = 0;
  uint1_t word_rd_en = 0;
  uint32_t i;
  for(i=0;i<4;i+=1){
    word_wr_en |= wr_byte_ens[i];
    word_rd_en |= rd_byte_ens[i];
  }

  // Account for data memory being mapped to upper physical addr range
  uint1_t is_dmem;
  uint1_t is_mmio;
  is_dmem = rw_addr(DMEM_ADDR_BIT_CHECK);
  is_mmio = rw_addr(MEM_MAP_ADDR_BIT_CHECK);
  if((~is_dmem & ~is_mmio)&(word_wr_en|word_rd_en)){
    printf("Error: mem_out_of_range memory address=%d is not for dmem or mmio?\n", rw_addr);
    mem_out.mem_out_of_range = 1;
  }
  if(is_dmem){
    rw_addr &= ~DMEM_BASE_ADDR;
  }
  // (note limits mmio range to upper 1/4 to full half fine for now...)

  // Convert byte addresses to 4-byte word index
  // do extra logic to account for how byte enables changes
  // assume is "aligned" to fit in one memory 32b word access?
  uint32_t mem_rw_word_index = rw_addr >> 2;
  uint2_t byte_mux_sel = rw_addr(1,0);
  uint1_t zeros[4] = {0,0,0,0};
  uint1_t rd_word_byte_ens[4] = rd_byte_ens;
  uint1_t wr_word_byte_ens[4] = wr_byte_ens;
  uint32_t wr_word = wr_data;
  if(byte_mux_sel==3){
    ARRAY_SHIFT_INTO_BOTTOM(rd_word_byte_ens, 4, zeros, 3)
    ARRAY_SHIFT_INTO_BOTTOM(wr_word_byte_ens, 4, zeros, 3)
    wr_word = wr_data << (3*8);
    // Check for dropped data in upper bytes
    if(rd_byte_ens[3]|rd_byte_ens[2]|rd_byte_ens[1]|
       wr_byte_ens[3]|wr_byte_ens[2]|wr_byte_ens[1])
    {
      printf("Error: mem_out_of_range unaligned access! addr=%d upper 3 bytes dropped\n",rw_addr);
      mem_out.mem_out_of_range = 1;
    }
  }else if(byte_mux_sel==2){
    ARRAY_SHIFT_INTO_BOTTOM(rd_word_byte_ens, 4, zeros, 2)
    ARRAY_SHIFT_INTO_BOTTOM(wr_word_byte_ens, 4, zeros, 2)
    wr_word = wr_data << (2*8);
    // Check for dropped data in upper bytes
    if(rd_byte_ens[3]|rd_byte_ens[2]|
       wr_byte_ens[3]|wr_byte_ens[2])
    {
      printf("Error: mem_out_of_range unaligned access! addr=%d upper 2 bytes dropped\n",rw_addr);
      mem_out.mem_out_of_range = 1;
    }
  }else if(byte_mux_sel==1){
    ARRAY_SHIFT_INTO_BOTTOM(rd_word_byte_ens, 4, zeros, 1)
    ARRAY_SHIFT_INTO_BOTTOM(wr_word_byte_ens, 4, zeros, 1)
    wr_word = wr_data << (1*8);
    // Check for dropped data in upper bytes
    if(rd_byte_ens[3]|
       wr_byte_ens[3])
    {
      printf("Error: mem_out_of_range unaligned access! addr=%d upper byte dropped\n",rw_addr);
      mem_out.mem_out_of_range = 1;
    }
  }

  // Check for write to memory mapped IO addresses
  riscv_mmio_mod_out_t mem_map_out = riscv_mem_map(
    // TODO replace user func addr param with index since always 32b aligned
    mem_rw_word_index<<2, 
    wr_word,
    wr_word_byte_ens,
    rd_word_byte_ens,
    valid,
    1 // always ready for output in free flowing pipeline dmem
    #ifdef riscv_mem_map_inputs_t
    , mem_map_inputs
    #endif
  );
  if(is_mmio){
    if(mem_map_out.addr_is_mapped){
      if(word_wr_en) printf("Memory mapped IO store addr=0x%X\n", rw_addr);
      if(word_rd_en) printf("Memory mapped IO load addr=0x%X\n", rw_addr); 
    }else{
      printf("Error: mem_out_of_range MMIO access to unmapped address=%d?\n", rw_addr);
      mem_out.mem_out_of_range = 1;
    }
  }

  #ifdef riscv_mem_map_outputs_t
  mem_out.mem_map_outputs = mem_map_out.outputs;
  #endif
  
  // Mem map write does not write actual RAM memory
  for(i=0;i<4;i+=1){
    wr_word_byte_ens[i] &= ~mem_map_out.addr_is_mapped;
    word_wr_en &= ~mem_map_out.addr_is_mapped;
    word_rd_en &= ~mem_map_out.addr_is_mapped;
  }  

  // Sanity check, stop sim if out of range access
  if((mem_rw_word_index >= RISCV_DMEM_NUM_WORDS) & (word_wr_en | word_rd_en)){
    printf("Error: mem_out_of_range large addr %d\n",rw_addr);
    mem_out.mem_out_of_range = 1;
  }

  // The single RAM instance
  riscv_dmem_ram_out_t ram_out = riscv_dmem_ram(mem_rw_word_index,
                                      wr_word, wr_word_byte_ens, valid);
  uint32_t mem_rd_data = ram_out.rd_data0;
  mem_out.valid = ram_out.valid0;

  // Determine output memory read data
  // Mem map read comes from memory map module not RAM memory
  if(mem_map_out.addr_is_mapped){
    mem_rd_data = mem_map_out.rd_data;
    mem_out.valid = mem_map_out.valid;
  }
  // Shift read data to account for conversion to 32b word index access
  if(byte_mux_sel==3){
    mem_rd_data = mem_rd_data >> (8*3);
  }else if(byte_mux_sel==2){
    mem_rd_data = mem_rd_data >> (8*2);
  }else if(byte_mux_sel==1){
    mem_rd_data = mem_rd_data >> (8*1);
  }  
  // Apply read enable byte enables to clear unused bits
  // Likely unecessary since sign extend done in reg wr stage?
  if(rd_byte_ens[3] & rd_byte_ens[2] & rd_byte_ens[1] & rd_byte_ens[0]){
    mem_rd_data = mem_rd_data; // No byte truncating
  }else if(rd_byte_ens[1] & rd_byte_ens[0]){
    // Lower two bytes only
    mem_rd_data = uint16_uint16(0, mem_rd_data(15,0));
  }else {
    // Lower single bytes only (or no read)
    mem_rd_data = uint24_uint8(0, mem_rd_data(7,0));
  }
  // Final mem rd data assignment to output
  mem_out.rd_data = mem_rd_data;
  return mem_out;
}
#endif // /\ Pipelineable DMEM /\


// Copy of above dmem module 
// modified to no longer be a pipeline
// in support FSM style memory access that takes variable amount of time
#ifdef RISCV_DMEM_NO_AUTOPIPELINE
#ifdef RISCV_DMEM_1_CYCLE
riscv_dmem_out_t riscv_dmem(
  uint32_t rw_addr,
  uint32_t wr_data,
  uint1_t wr_byte_ens[4],
  uint1_t rd_byte_ens[4],
  uint1_t valid_in, // aka start
  uint1_t ready_for_outputs
  #ifdef riscv_mem_map_inputs_t
  , riscv_mem_map_inputs_t mem_map_inputs
  #endif
){
  riscv_dmem_out_t mem_out;

  // Two states like CPU
  static uint1_t is_START_state = 1; // Otherwise is END

  // Registers to hold things supplied during start state
  // but needed later during end state
  // To adjust output of whatever memory
  static uint1_t rd_byte_ens_reg[4]; 
  // Decode mem hardware type
  static uint1_t is_dmem;
  static uint1_t is_mmio;
  if(valid_in){
    rd_byte_ens_reg = rd_byte_ens;
    is_dmem = rw_addr(DMEM_ADDR_BIT_CHECK);
    is_mmio = rw_addr(MEM_MAP_ADDR_BIT_CHECK);
    if(~is_dmem & ~is_mmio){
      printf("Error: memory address=%d is not for dmem or mmio?\n", rw_addr);
      mem_out.mem_out_of_range = 1;
    }
  }
  // Overide input signal with valid gated input reg contents
  if(~valid_in){
    rd_byte_ens = rd_byte_ens_reg;
  }
   
  // Account for data memory being mapped to upper physical addr range
  if(is_dmem){
    rw_addr &= ~DMEM_BASE_ADDR;
  }
  // Convert byte addresses to 4-byte word index
  uint32_t mem_rw_word_index = rw_addr >> 2;
  uint2_t byte_mux_sel = rw_addr(1,0);

  // Write or read helper flags
  uint1_t word_wr_en = 0;
  uint1_t word_rd_en = 0;
  uint32_t i;
  for(i=0;i<4;i+=1){
    word_wr_en |= wr_byte_ens[i];
    word_rd_en |= rd_byte_ens[i];
  }

  // Extra logic to account for how byte enables changes
  // assume is "aligned" to fit in one memory 32b word access?
  uint1_t zeros[4] = {0,0,0,0};
  uint1_t rd_word_byte_ens[4] = rd_byte_ens;
  uint1_t wr_word_byte_ens[4] = wr_byte_ens;
  uint32_t wr_word = wr_data;
  if(byte_mux_sel==3){
    ARRAY_SHIFT_INTO_BOTTOM(rd_word_byte_ens, 4, zeros, 3)
    ARRAY_SHIFT_INTO_BOTTOM(wr_word_byte_ens, 4, zeros, 3)
    wr_word = wr_data << (3*8);
    // Check for dropped data in upper bytes
    if(valid_in&(rd_byte_ens[3]|rd_byte_ens[2]|rd_byte_ens[1]|
      wr_byte_ens[3]|wr_byte_ens[2]|wr_byte_ens[1]))
    {
      printf("Error: mem_out_of_range unaligned access! addr=%d upper 3 bytes dropped\n",rw_addr);
      mem_out.mem_out_of_range = 1;
    }
  }else if(byte_mux_sel==2){
    ARRAY_SHIFT_INTO_BOTTOM(rd_word_byte_ens, 4, zeros, 2)
    ARRAY_SHIFT_INTO_BOTTOM(wr_word_byte_ens, 4, zeros, 2)
    wr_word = wr_data << (2*8);
    // Check for dropped data in upper bytes
    if(valid_in&(rd_byte_ens[3]|rd_byte_ens[2]|
      wr_byte_ens[3]|wr_byte_ens[2]))
    {
      printf("Error: mem_out_of_range unaligned access! addr=%d upper 2 bytes dropped\n",rw_addr);
      mem_out.mem_out_of_range = 1;
    }
  }else if(byte_mux_sel==1){
    ARRAY_SHIFT_INTO_BOTTOM(rd_word_byte_ens, 4, zeros, 1)
    ARRAY_SHIFT_INTO_BOTTOM(wr_word_byte_ens, 4, zeros, 1)
    wr_word = wr_data << (1*8);
    // Check for dropped data in upper bytes
    if(valid_in&(rd_byte_ens[3]|
      wr_byte_ens[3]))
    {
      printf("Error: mem_out_of_range unaligned access! addr=%d upper byte dropped\n",rw_addr);
      mem_out.mem_out_of_range = 1;
    }
  }

  // Start state signalling into memories
  uint1_t dmem_valid_in;
  uint1_t mmio_valid_in;
  if(is_START_state){
    // Wait for valid input
    if(valid_in){
      if(is_dmem){
        dmem_valid_in = 1;
        // Sanity check, stop sim if out of range access for dmem
        if((mem_rw_word_index >= RISCV_DMEM_NUM_WORDS) & (word_wr_en | word_rd_en)){
          printf("Error: mem_out_of_range large addr %d\n",rw_addr);
          mem_out.mem_out_of_range = 1;
        }
      }
      if(is_mmio){
        mmio_valid_in = 1;
        if(word_wr_en) printf("Memory mapped IO store addr=0x%X started\n", rw_addr);
        if(word_rd_en) printf("Memory mapped IO load addr=0x%X started\n", rw_addr); 
      }
    }
    // Note: state transition out of START
    // depends on ready output from memory handled below
  }
  
  // Locally instatiated memory modules
  //  Primary dmem RAM instance
  riscv_dmem_ram_out_t ram_out = riscv_dmem_ram(mem_rw_word_index,
                                      wr_word, wr_word_byte_ens, dmem_valid_in);
  //  Memory mapped IO
  riscv_mmio_mod_out_t mem_map_out = riscv_mem_map(
    mem_rw_word_index<<2, 
    wr_word,
    wr_word_byte_ens,
    rd_word_byte_ens,
    mmio_valid_in,
    ready_for_outputs & is_mmio // MMIO ready for outputs when this module is
    #ifdef riscv_mem_map_inputs_t
    , mem_map_inputs
    #endif
  );
  #ifdef riscv_mem_map_outputs_t
  mem_out.mem_map_outputs = mem_map_out.outputs;
  #endif

  // Start state transitions to end if selected memory accepted valid input as ready
  if(is_START_state){
    // Wait for valid input
    if(valid_in){
      if(is_dmem){
        // DMEM is always ready bram
        // (ready is output ready, mostly can assume)
        mem_out.ready_for_inputs = ready_for_outputs;
        // just go to next state
        is_START_state = 0;
      }
      if(is_mmio){
        // Need to wait for MMIO to be ready for starting input
        // before moving to next state waiting to end and get output
        mem_out.ready_for_inputs = mem_map_out.ready_for_inputs;
        if(~mem_map_out.addr_is_mapped){
          printf("Error: MMIO access to unmapped address=%d?\n", rw_addr);
          mem_out.mem_out_of_range = 1;
        }
      }
      if(mem_out.ready_for_inputs){
        is_START_state = 0;
      }
    }
  }

  // End state signalling handling outputs from memory
  // Drive mem out valid and rd_data
  uint32_t mem_rd_data = 0;
  mem_out.valid = 0;
  if(~is_START_state){
    // Wait for valid output from selected memory hardware
    if(is_dmem){
      mem_rd_data = ram_out.rd_data0;
      mem_out.valid = ram_out.valid0;
    }
    if(is_mmio){
      mem_rd_data = mem_map_out.rd_data;
      mem_out.valid = mem_map_out.valid;
    }
    // Back to start once output happened
    if(mem_out.valid & ready_for_outputs){
      is_START_state = 1;
    }
  }
  
  // Shift read data to account for conversion to 32b word index access
  if(byte_mux_sel==3){
    mem_rd_data = mem_rd_data >> (8*3);
  }else if(byte_mux_sel==2){
    mem_rd_data = mem_rd_data >> (8*2);
  }else if(byte_mux_sel==1){
    mem_rd_data = mem_rd_data >> (8*1);
  }  
  // Apply read enable byte enables to clear unused bits
  // Likely unecessary since sign extend done in reg wr stage?
  if(rd_byte_ens[3] & rd_byte_ens[2] & rd_byte_ens[1] & rd_byte_ens[0]){
    mem_rd_data = mem_rd_data; // No byte truncating
  }else if(rd_byte_ens[1] & rd_byte_ens[0]){
    // Lower two bytes only
    mem_rd_data = uint16_uint16(0, mem_rd_data(15,0));
  }else {
    // Lower single bytes only (or no read)
    mem_rd_data = uint24_uint8(0, mem_rd_data(7,0));
  }
  // Final mem rd data assignment to output
  mem_out.rd_data = mem_rd_data;

  return mem_out;
}
#endif
#endif