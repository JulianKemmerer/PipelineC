#include "uintN_t.h"

// LEDs for debug/output
#include "leds/leds_port.c"
#include "buttons/buttons.c"

// Include logic for Xilinx Memory Interface Generator w/ AXI interface
#include "axi_xil_mem.c" 

// Example memory test that writes a test pattern
// and then reads the same data back
#define TEST_DATA_SIZE 4 // Single 32b AXI word
#define TEST_ADDR_MAX (XIL_MEM_ADDR_MAX-TEST_DATA_SIZE+1)
typedef enum mem_test_state_t
{
  WAIT_RESET,
  WRITES,
  READS,
  FAILED
}mem_test_state_t;

// The memory test process, same clock as generated memory interface
MAIN_MHZ(app, XIL_MEM_MHZ)
void app()
{
  // State registers
  static mem_test_state_t mem_test_state;
  static axi_addr_t test_addr;
  static uint32_t test_data;

  // Output wire into memory controller, default zeros
  app_to_xil_mem = NULL_APP_TO_XIL_MEM;
  
  // Next values
  axi_addr_t next_addr = test_addr + TEST_DATA_SIZE;
  uint32_t next_test_data = test_data + 1;

  // Memory reset/calbration signalling
  uint1_t mem_rst_done
      = (buttons==0) & !xil_mem_to_app.ui_clk_sync_rst & xil_mem_to_app.init_calib_complete;
  
  // MEM TEST FSM
  if(mem_test_state==WAIT_RESET)
  {
    leds = 0;
    // Wait for DDR reset+calibration to be done
    if(mem_rst_done)
    {
      // Start test
      mem_test_state = WRITES;
      test_addr = 0;
      test_data = 0;
    }
  }
  else if(mem_test_state==WRITES)
  {
    leds = 0b0011;
    // Use logic for AXI write of single 32b word 
    // (slow, not burst and waits for response)
    axi32_write_logic_outputs_t axi32_write_logic_outputs 
      = axi32_write_logic(test_addr, test_data, 1, xil_mem_to_app.axi_dev_to_host);
    // Write logic drives AXI bus
    app_to_xil_mem.axi_host_to_dev = axi32_write_logic_outputs.to_dev;
    // Wait for write to finish
    if(axi32_write_logic_outputs.done)
    {
      // Update test data for next iter
      test_data = next_test_data;
      if(test_addr < TEST_ADDR_MAX)
      {
        // Next test address
        test_addr = next_addr;
      }
      else
      {
        // Done with address space
        // Begin test of reads
        test_addr = 0;
        test_data = 0;
        mem_test_state = READS;
      }
    }
  }
  else if(mem_test_state==READS)
  {
    leds = 0b1100;
    // Use logic for AXI read of single 32b word 
    // (slow, not burst and waits for response)
    axi32_read_logic_outputs_t axi32_read_logic_outputs 
      = axi32_read_logic(test_addr, 1, xil_mem_to_app.axi_dev_to_host);
    // Read logic drives AXI bus
    app_to_xil_mem.axi_host_to_dev = axi32_read_logic_outputs.to_dev;
    // Wait for read to finish
    if(axi32_read_logic_outputs.done)
    {
      // Compare read data vs expected test data
      if(axi32_read_logic_outputs.data == test_data)
      {
        // Good compare, update test data for next iter
        test_data = next_test_data;
        if(test_addr < TEST_ADDR_MAX)
        {
          // Next test address
          test_addr = next_addr;
        }
        else
        {
          // Done with test, passed, repeat test
          mem_test_state = WAIT_RESET;
        }
      }
      else
      {
        // Bad compare, test failed, stop
        mem_test_state = FAILED;
      }
    }
  }
  else
  {
    // FAILED
    leds = 0b1111;
  }
  
  // Resets
  if(!mem_rst_done)
  {
    mem_test_state = WAIT_RESET;
  }
}
