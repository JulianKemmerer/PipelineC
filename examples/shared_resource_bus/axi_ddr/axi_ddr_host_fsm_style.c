#include "uintN_t.h"

// LEDs for debug/output
#include "leds/leds_port.c"

// AXI read+write with shared bus
#include "axi_xil_mem.c"

// Example memory test that writes a test pattern
// and then reads the same data back
#define TEST_DATA_SIZE 4 // Single 32b AXI word
#define TEST_ADDR_MAX (XIL_MEM_ADDR_MAX-TEST_DATA_SIZE+1)

void app()
{
  // Test loop
  uint1_t test_passing = 1;
  __clk();
  while(test_passing)
  {
    // Wait for reset to be done
    leds = 0;
    __clk();
    while(!xil_mem_rst_done)
    {
      __clk();
    }

    // Write test pattern
    leds = 0b0011;
    axi_addr_t test_addr = 0;
    uint32_t test_data = 0;
    __clk();
    while(test_addr < TEST_ADDR_MAX)
    {
      axi_write(test_addr, test_data);
      test_addr += TEST_DATA_SIZE;
      test_data += 1;
      __clk();
    }
    
    // Read back test pattern
    leds = 0b1100;
    test_addr = 0;
    test_data = 0;
    __clk();
    while((test_addr < TEST_ADDR_MAX) & test_passing)
    {
      uint32_t read_data = axi_read(test_addr);
      __clk();
      // Compare read data vs expected test data
      if(read_data != test_data)
      {
        // Bad compare, test failed, stop
        test_passing = 0;
      }
      // Next address
      test_addr += TEST_DATA_SIZE;
      test_data += 1;
      //__clk();
    }
  }

  // Test failed if got here
  while(1)
  {
    leds = 0b1111;
    __clk();
  }
}

// Derived fsm from app (TODO code gen...)
#include "app_FSM.h"
// Wrap up app FSM as top level
// The memory test process, same clock as generated memory interface
MAIN_MHZ(app_wrapper, SHARED_AXI_XIL_MEM_HOST_CLK_MHZ)
void app_wrapper()
{
  app_INPUT_t i;
  i.input_valid = 1;
  i.output_ready = 1;
  app_OUTPUT_t o = app_FSM(i);
}