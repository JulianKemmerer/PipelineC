// Combined instruction and data memory
#include "uintN_t.h"
#include "intN_t.h"
#include "compiler.h"
#include "debug_port.h"

// Combined instruction and data memory initialized from gcc compile
#define MEM_SIZE_IN_BYTES 2048
#define MEM_NUM_WORDS (MEM_SIZE_IN_BYTES/4)
#include "gcc_test/mem_init.h"
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
  constant SIZE : integer := " xstr(MEM_NUM_WORDS) "; \n\
  type ram_t is array(0 to SIZE-1) of unsigned(31 downto 0); \n\
  signal the_ram : ram_t := " MEM_INIT "; \n\
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

// Memory mapped IO modules to drive hardware wires, ex. debug ports, devices
#include "mem_map.c"

// Split main memory the_mem into two parts,
// one read port for instructions, one r/w port for data mem
typedef struct mem_out_t
{
  uint32_t inst_read;
  uint32_t mem_read_write;
}mem_out_t;
typedef struct mem_rw_in_t{
  uint32_t addr;
  uint32_t wr_data;
  uint1_t wr_byte_ens[4];
}mem_rw_in_t;
DEBUG_OUTPUT_DECL(uint1_t, mem_out_of_range) // Exception, stop sim
mem_out_t mem(
  uint32_t rd_addr,
  mem_rw_in_t mem_rw
){
  // Check for write to memory mapped IO addresses
  mem_map_out_t mem_map_out = mem_map_module(
    mem_rw.addr,
    mem_rw.wr_data,
    mem_rw.wr_byte_ens);
  
  // Mem map write does not write actual RAM memory
  uint32_t i;
  for(i=0;i<4;i+=1){
    mem_rw.wr_byte_ens[i] &= !mem_map_out.addr_is_mapped;
  }  

  // Convert byte addresses to aligned 4-byte word address
  uint32_t mem_rw_word_index = mem_rw.addr >> 2;
  uint32_t rd_addr_word_index = rd_addr >> 2;

  // Sanity check, stop sim if out of range access
  if((mem_rw_word_index >= MEM_NUM_WORDS) & mem_rw.wr_byte_ens[0]){
    mem_out_of_range = 1;
  }

  // The single RAM instance with connections splitting in two
  the_mem_outputs_t ram_out = the_mem(mem_rw_word_index,
                                      mem_rw.wr_data, mem_rw.wr_byte_ens, 1,
                                       rd_addr, 1);
  mem_out_t mem_out;
  mem_out.mem_read_write = ram_out.rd_data0;
  mem_out.inst_read = ram_out.rd_data1;

  // Mem map read comes from memory map module not RAM memory
  if(mem_map_out.addr_is_mapped){
    mem_out.mem_read_write = mem_map_out.rd_data;
  }

  return mem_out;
}
MAIN_SPLIT2(
  mem_out_t,
  mem,
  inst_read,
  uint32_t,
  uint32_t,
  mem_read_write,
  mem_rw_in_t,
  uint32_t
)
