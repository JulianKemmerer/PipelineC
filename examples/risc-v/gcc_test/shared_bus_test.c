#include <stdint.h>
#include "mem_map.h"

#define MEM_SIZE 268435456 // 2^28 bytes , 256MB DDR3 = 28b address

void main() {
	while(1){
    // Light LEDs to show working
    *LED = 1;
    // Write the entire memory space with data=address
    uint32_t addr;
    for(addr=0; addr<MEM_SIZE; addr+=sizeof(uint32_t)){
      ram_write(addr, addr);
    }
    // Toggle LEDs to show rate
    *LED = 0;
    // Read it back
    for(addr=0; addr<MEM_SIZE; addr+=sizeof(uint32_t)){
      uint32_t data = ram_read(addr);
      if(data!=addr){
        *LED = 0; // Stay off
        break;
      }
    }
	}
}
