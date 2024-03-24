#include <stdint.h>
#include "mem_map.h"

#define MEM_SIZE 268435456 // 2^28 bytes , 256MB DDR3 = 28b address

void main() {
  int32_t passing = 1;
  *LED = 1;
  while(passing){
    // Read and write the entire memory space with data=address
    //  Start several writes until hardware pushes back
    //  Then switch over to finishing writes until hardware says no more
    //  Then try to start some reads after any finished writes
    //  Try to finish some reads
    //  And repeat until all writes and read are done
    int32_t wr_start_addr = 0;
    int32_t wr_finish_addr = 0;
    int32_t rd_start_addr = 0;
    int32_t rd_finish_addr = 0;
    while(rd_finish_addr<MEM_SIZE){
      // Start some writes, data=addr
      while((wr_start_addr<MEM_SIZE) && try_start_ram_write(wr_start_addr, wr_start_addr)){
        wr_start_addr += sizeof(uint32_t);
      }
      // Finish some writes
      while(try_finish_ram_write()){
        wr_finish_addr += sizeof(uint32_t);
      }
      // Start some reads from addrs that have been written
      while((rd_start_addr<wr_finish_addr) && try_start_ram_read(rd_start_addr)){
        rd_start_addr += sizeof(uint32_t);
      }
      // Finish some reads
      ram_rd_try_t rd_try;
      do{
        rd_try = try_finish_ram_read();
        if(rd_try.valid){
          // Compare
          if(rd_try.data != rd_finish_addr){
            // Mismatch
            *LED = 0; // Stay off
            rd_finish_addr = MEM_SIZE; // End test
            passing = 0; // Failed
            break;
          }else{
            // Next
            rd_finish_addr += sizeof(uint32_t);
          }
        }
      }while(rd_try.valid);
    }
    // Toggle LEDs to show working
    *LED = ~*LED;
    // Mem test time = 4:30
  }
}
