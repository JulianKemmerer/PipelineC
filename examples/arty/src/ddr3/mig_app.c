#include "compiler.h"
#include "wire.h"
#include "../leds/leds.c"
#include "xil_mig.c"

// Example memory test that writes a test pattern to DDR
// and then reads the same data back

typedef enum mem_test_state_t
{
  WAIT_RESET,
  WRITES,
  READ_REQ,
  READ_RESP,
  FAILED
}mem_test_state_t;
mem_test_state_t mem_test_state;

// A single test data unit is the size of one data transfer
#define TEST_DATA_SIZE XIL_MIG_DATA_SIZE
#define TEST_ADDR_MAX (XIL_MIG_ADDR_MAX-TEST_DATA_SIZE+1)
// Bytes wrapped in a struct for returning since C syntax
typedef struct test_data_t
{
  uint8_t data[TEST_DATA_SIZE];  
}test_data_t;
test_data_t INIT_TEST_DATA()
{
  test_data_t rv;
  uint32_t i;
  for(i=0;i<TEST_DATA_SIZE;i+=1)
  {
    rv.data[i] = i;
  }
  return rv;
}

// State registers
xil_mig_addr_t test_addr;
test_data_t test_data;

// The memory test process, same clock as generated memory interface
#pragma MAIN_MHZ app xil_mig_module
void app()
{
  // Status leds indicate state
  uint1_t led[4];
  led[0] = mem_test_state==WAIT_RESET;
  led[1] = mem_test_state==WRITES;
  led[2] = (mem_test_state==READ_REQ) | (mem_test_state==READ_RESP);
  led[3] = (mem_test_state==READ_RESP);
  
  // Input read outputs wires from memory controller
  xil_mig_to_app_t from_mem;
  WIRE_READ(xil_mig_to_app_t, from_mem, xil_mig_to_app)

  // Output wire into memory controller
  xil_app_to_mig_t to_mem = XIL_APP_TO_MIG_T_NULL();
  // Defaults/data path connections
  to_mem.wdf_data = test_data.data; //uint8_array16_le
  to_mem.addr = test_addr;
  
  // Next values
  xil_mig_addr_t next_addr = test_addr + TEST_DATA_SIZE;
  uint8_t next_test_data[TEST_DATA_SIZE];
  uint32_t i;
  for(i=0;i<TEST_DATA_SIZE;i+=1)
  {
    next_test_data[i] = test_data.data[i]+1;
  }  
  
  // MEM TEST FSM
  if(mem_test_state==WAIT_RESET)
  {
    // Wait for DDR reset to be done
    uint1_t mem_rst_done = !from_mem.ui_clk_sync_rst & from_mem.init_calib_complete;
    if(mem_rst_done)
    {
      mem_test_state = WRITES;
    }
    // Start test
    test_addr = 0;
    test_data = INIT_TEST_DATA();
  }
  else if(mem_test_state==WRITES)
  {
    // Prepare the write of the test data
    to_mem.cmd = XIL_MIG_CMD_WRITE;
    to_mem.wdf_end = 1; // TODO bursts later?
    
    // If mem controller was ready, go to next test word/state
    uint1_t mem_rdy = from_mem.rdy & from_mem.wdf_rdy;
    if(mem_rdy)
    {
      // Enable the write only if ready //TODO not good practice
      to_mem.en = 1;
      to_mem.wdf_wren = 1;
      
      // Update test data for next iter
      test_data.data = next_test_data;
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
        test_data = INIT_TEST_DATA();
        mem_test_state = READ_REQ;
      }
    }
  }
  else if(mem_test_state==READ_REQ)
  {
    // Prepare the read of test data
    to_mem.cmd = XIL_MIG_CMD_READ;
    // Enable the read
    to_mem.en = 1;
    
    // If mem controller was ready, wait for response
    if(from_mem.rdy)
    {
      mem_test_state = READ_RESP;
    }
  }
  else if(mem_test_state==READ_RESP)
  {   
    // Wait for valid read data returned
    if(from_mem.rd_data_valid)
    {
      // Compare read data vs expected test data
      uint1_t matches[TEST_DATA_SIZE];
      for(i=0;i<TEST_DATA_SIZE;i+=1)
      {
        matches[i] = from_mem.rd_data[i] == test_data.data[i];
      }
      uint1_t match = uint1_array_and16(matches);
      
      if(match)
      {
        // Update test data for next iter
        test_data.data = next_test_data;
        if(test_addr < TEST_ADDR_MAX)
        {
          // Next test address
          test_addr = next_addr;
          // Make read request
          mem_test_state = READ_REQ;
        }
        else
        {
          // Done with test, passed, repeat test
          mem_test_state = WAIT_RESET;
        }
      }
      else
      {
        // Not match, test failed
        mem_test_state = FAILED;
      }
    }
  }
  else
  {
    // FAILED
    led[0] = 1;
    led[1] = 1;
    led[2] = 1;
    led[3] = 1;
  }
  
  // Resets
  if(from_mem.ui_clk_sync_rst)
  {
    mem_test_state = WAIT_RESET;
  }
  
  // Drive wires into memory controller
  WIRE_WRITE(xil_app_to_mig_t, xil_app_to_mig, to_mem)
  
  // Drive the leds
  WIRE_WRITE(uint4_t, leds, uint1_array4_le(led)) // leds (global wire) = led (local) wire
}
