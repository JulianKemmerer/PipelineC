// Combined instruction and data memory, used with risc-v_decl.h
#include "uintN_t.h"
#include "intN_t.h"
#include "compiler.h"

#include "mem_map.h"

// Combined instruction and data memory initialized from gcc compile
#define RISCV_MEM_NUM_WORDS (RISCV_MEM_SIZE_BYTES/4)

// Need a RAM with one read port for instructions, one r/w port for data mem
// Was using ram.h DECL_RAM_DP_RW_R_0 macro, 
// but does not include byte enables needed for RISC-V SH and SB
// So manually copied that macro def and modified vhdl here to add byte enables:
typedef struct the_mem_outputs_t
{
  uint32_t addr0;
  uint32_t wr_data0; uint1_t wr_byte_ens0[4];
  uint32_t rd_data0;
  uint1_t valid0;
  uint32_t addr1;
  uint32_t rd_data1;
  uint1_t valid1;
}the_mem_outputs_t;
the_mem_outputs_t the_mem(
  uint32_t addr0,
  uint32_t wr_data0, uint1_t wr_byte_ens0[4],
  uint1_t valid0,
  uint32_t addr1,
  uint1_t valid1
){
  __vhdl__("\n\
  constant SIZE : integer := " xstr(RISCV_MEM_NUM_WORDS) "; \n\
  type ram_t is array(0 to SIZE-1) of unsigned(31 downto 0); \n\
  signal the_ram : ram_t := " RISCV_MEM_INIT "; \n\
  -- Limit zero latency comb. read addr range to SIZE \n\
  -- since invalid addresses can occur as logic propogates \n\
  -- (this includes out of int32 range u32 values) \n\
  signal addr0_s : integer range 0 to SIZE-1 := 0; \n\
  signal addr1_s : integer range 0 to SIZE-1 := 0; \n\
begin \n\
  process(all) begin \n\
    addr0_s <= to_integer(addr0(30 downto 0)) \n\
    -- synthesis translate_off \n\
    mod SIZE \n\
    -- synthesis translate_on \n\
    ; \n\
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
  return_output.addr1 <= addr1; \n\
  return_output.rd_data1 <= the_ram(addr1_s); \n\
  return_output.valid1 <= valid1; \n\
");
}


// Split main memory the_mem into two parts,
// one read port for instructions, one r/w port for data mem
typedef struct mem_out_t
{
  uint32_t inst;
  uint32_t rd_data;
  uint1_t mem_out_of_range; // Exception, stop sim
  #ifdef riscv_mem_map_outputs_t
  riscv_mem_map_outputs_t mem_map_outputs;
  #endif
}mem_out_t;
mem_out_t mem(
  uint32_t inst_addr,
  uint32_t rw_addr,
  uint32_t wr_data,
  uint1_t wr_byte_ens[4]
  #ifdef riscv_mem_map_inputs_t
  , riscv_mem_map_inputs_t mem_map_inputs
  #endif
){
  // Check for write to memory mapped IO addresses
  riscv_mmio_mod_out_t mem_map_out = riscv_mem_map(
    rw_addr,
    wr_data,
    wr_byte_ens
    #ifdef riscv_mem_map_inputs_t
    , mem_map_inputs
    #endif
  );
  mem_out_t mem_out;
  #ifdef riscv_mem_map_outputs_t
  mem_out.mem_map_outputs = mem_map_out.outputs;
  #endif
  
  // Mem map write does not write actual RAM memory
  uint32_t i;
  for(i=0;i<4;i+=1){
    wr_byte_ens[i] &= !mem_map_out.addr_is_mapped;
  }  

  // Convert byte addresses to aligned 4-byte word address
  uint32_t mem_rw_word_index = rw_addr >> 2;
  //uint32_t inst_addr_word_index = inst_addr >> 2;

  // Sanity check, stop sim if out of range access
  if((mem_rw_word_index >= RISCV_MEM_NUM_WORDS) & wr_byte_ens[0]){
    mem_out.mem_out_of_range = 1;
  }

  // The single RAM instance
  the_mem_outputs_t ram_out = the_mem(mem_rw_word_index,
                                      wr_data, wr_byte_ens, 1,
                                       inst_addr, 1);
  mem_out.rd_data = ram_out.rd_data0;
  mem_out.inst = ram_out.rd_data1;

  // Mem map read comes from memory map module not RAM memory
  if(mem_map_out.addr_is_mapped){
    mem_out.rd_data = mem_map_out.rd_data;
  }

  return mem_out;
}