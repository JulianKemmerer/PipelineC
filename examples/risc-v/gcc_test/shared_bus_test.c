#include <stdint.h>
#include "mem_map.h"

#define MEM_SIZE 268435456 // 2^28 bytes , 256MB DDR3 = 28b address

void main() {
  // Calculate memory bounds based on which core you are
  // Chunk size in bytes rounded to u32 4 byte units
  uint32_t chunk_size = ((MEM_SIZE/NUM_CORES)/sizeof(uint32_t))*sizeof(uint32_t);
  uint32_t start_addr = *CORE_ID * chunk_size;
  // Adjust for if mem size divides unevenly
  uint32_t chunks_sum = chunk_size * NUM_CORES;
  // Last core gets different chunk size
  int32_t last_chunk_extra = MEM_SIZE - chunks_sum;
  int32_t last_chunk_size = chunk_size + last_chunk_extra;
  if(*CORE_ID==(NUM_CORES-1)){
    chunk_size = last_chunk_size;
  }
  uint32_t end_addr = start_addr + chunk_size;

  // Do mem test
  *LED = 1;
  int32_t passing = 1;
  while(passing){
    // Read and write the entire memory space with data=address
    //  Try to start a write, then try to finish a write
    //  then try to start a read and try to finish a read
    //  And repeat until all writes and read are done
    int32_t wr_start_addr = start_addr;
    int32_t wr_finish_addr = start_addr;
    int32_t rd_start_addr = start_addr;
    int32_t rd_finish_addr = start_addr;
    while(rd_finish_addr<end_addr){
      // Try to start a write, data=addr
      if((wr_start_addr<end_addr) && try_start_ram_write(wr_start_addr, wr_start_addr)){
        wr_start_addr += sizeof(uint32_t);
      }
      // Try to finish a write
      if((wr_finish_addr<wr_start_addr) && try_finish_ram_write()){
        wr_finish_addr += sizeof(uint32_t);
      }
      // Try to start a read from addr that has been written
      if((rd_start_addr<wr_finish_addr) && try_start_ram_read(rd_start_addr)){
        rd_start_addr += sizeof(uint32_t);
      }
      // Try to finish a read
      if(rd_finish_addr<rd_start_addr){
        ram_rd_try_t rd_try = try_finish_ram_read();
        if(rd_try.valid){
          // Compare
          if(rd_try.data != rd_finish_addr){
            // Mismatch
            *LED = 0; // Stay off
            rd_finish_addr = end_addr; // End test
            passing = 0; // Failed
            break;
          }else{
            // Next
            rd_finish_addr += sizeof(uint32_t);
          }
        }
      }
    }
    // Toggle LEDs to show working
    *LED = ~*LED;
    // Mem test time = 12cores=23sec,8cores=35sec,4cores=1:09,1core=4:36
  }
  *RETURN_OUTPUT = passing; // Halt sim/light debug leds maybe
  return;
}
