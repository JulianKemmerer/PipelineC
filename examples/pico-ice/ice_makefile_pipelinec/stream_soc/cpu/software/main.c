#include <stdint.h>
#include <stdlib.h>
#include "uintN_t.h"

// Memory map shared between software and hardware
#include "../mem_map.h"

// Device specific functionality using memory map
#include "../../clock/software/device.h" // for wait_ms

int axil_test(){
  int passed = 1;
  static uint32_t test_w = 0;
  static uint32_t test_r = 0;
  for (int i = 0; (i < 100000) && passed; i++)
  {  
    for (uint32_t w = 0; w < AXIL_DEMO_NWORDS; w++)
    {
      *(uint32_t*)(&my_axil_test->word_bytes[w]) = test_w;
      test_w += 1;
    }
    for (uint32_t w = 0; w < AXIL_DEMO_NWORDS; w++)
    {
      uint32_t r = *(uint32_t*)(&my_axil_test->word_bytes[w]);
      if(r!=test_r)passed=0;
      test_r += 1;
    }
  }
  return passed;
}

void main() {
  my_mm_regs->led_g = 0;
  my_led_b->led_on = 0;
  while(1){
    my_mm_regs->led_g = ~my_mm_regs->led_g;
    my_led_b->led_on = ~my_led_b->led_on;
    wait_ms(1);
    if(!axil_test()) break;
  }
}
