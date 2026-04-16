#include <stdint.h>
#include <stdlib.h>
#include "uintN_t.h"

// Memory map shared between software and hardware
#include "../mem_map.h"

// Device specific functionality using memory map
#include "../../clock/software/device.h" // for wait_ms

void main() {
  while(1){
    my_mm_regs->led = ~my_mm_regs->led;
    wait_ms(500);
  }
}
