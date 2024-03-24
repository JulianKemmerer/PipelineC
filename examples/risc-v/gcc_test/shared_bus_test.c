#include <stdint.h>
#include "mem_map.h"

#define MEM_SIZE 268435456 // 2^28 bytes , 256MB DDR3 = 28b address

void main() {
  int32_t passing = 1;
  while(passing){
    // Light LEDs to show working
    *LED = 1;
    // Write the entire memory space with data=address
    //  Start several writes until hardware pushes back
    //  Then switch over to finishing writes until hardware says no more
    //  And repeat until all writes are finished
    int32_t start_addr = 0;
    int32_t finish_addr = 0;
    while(finish_addr<MEM_SIZE)
    {
      // Start some writes
      while((start_addr<MEM_SIZE) && try_start_ram_write(start_addr, start_addr))
      {
        start_addr += sizeof(uint32_t);
      }
      // Finish some writes
      while(try_finish_ram_write())
      {
        finish_addr += sizeof(uint32_t);
      }
    }
    // Similar for read side
    start_addr = 0;
    finish_addr = 0;
    // Toggle LEDs to show rate
    *LED = 0;
    while(finish_addr<MEM_SIZE)
    {
      // Start some reads
      while((start_addr<MEM_SIZE) && try_start_ram_read(start_addr))
      {
        start_addr += sizeof(uint32_t);
      }
      // Finish some reads
      ram_rd_try_t rd_try;
      do
      {
        rd_try = try_finish_ram_read();
        if(rd_try.valid){
          // Compare
          if(rd_try.data != finish_addr){
            // Mismatch
            *LED = 0; // Stay off
            finish_addr = MEM_SIZE; // End test
            passing = 0; // Failed
            break;
          }else{
            // Next
            finish_addr += sizeof(uint32_t);
          }
        }
      }while(rd_try.valid);
    }
    // Mem test time = wr 112sec, 160sec rd
  }
}
