//#pragma PART "xc7a35ticsg324-1l"
#pragma PART "LFE5U-85F-6BG381C8"

// Similar to async_clock_crossing.c except is a sync global fifo
#pragma MAIN_MHZ process_a 100.0
#pragma MAIN_MHZ process_b 100.0

#include "uintN_t.h"
#include "leds/led0_3_ports.c"

// The fifos
#include "global_fifo.h"
// Write+read 2 'datas' in/out the fifo at a time
// (port sizes on each side of fifo)
#define data_t uint8_t
#define DATAS_PER_ITER 2
// Fifo depth=4
//data_t process_a_to_process_b[4];
//data_t process_b_to_process_a[4]; 
GLOBAL_FIFO_WIDTH_DEPTH(data_t, process_a_to_process_b, DATAS_PER_ITER, 256)
GLOBAL_FIFO_WIDTH_DEPTH(data_t, process_b_to_process_a, DATAS_PER_ITER, 256)
// TODO include 'wrapper' read+write N func names in macros?
#define process_a_to_process_b_WRITE_N process_a_to_process_b_WRITE_2
#define process_b_to_process_a_READ_N process_b_to_process_a_READ_2
#define process_b_to_process_a_WRITE_N process_b_to_process_a_WRITE_2
#define process_a_to_process_b_READ_N process_a_to_process_b_READ_2

void process_a()
{  
  // Drive leds with state, default lit
  static uint1_t power_on_reset = 1;
  static uint1_t test_failed = 0;
  uint1_t led = 1;
  if(test_failed)
  {
    led = 0;
  }
  led0 = led;
  led1 = !power_on_reset;
  
  // Send a test pattern into process_b
  static data_t test_data = 0;
  // Try to write test datas
  data_t wr_data[DATAS_PER_ITER];
  uint32_t i = 0;
  for(i = 0; i<DATAS_PER_ITER; i+=1)
  {
    wr_data[i] = test_data + i;
  }
  uint1_t wr_en = 1;
  // Reset input to fifo
  if(power_on_reset)
  {
    wr_en = 0;
  }
  process_a_to_process_b_write_t write = process_a_to_process_b_WRITE_N(wr_data, wr_en);
  // Did the write go through?
  if(write.ready)
  {
    // Next test data
    test_data += DATAS_PER_ITER;
  }
  // Reset statics
  if(power_on_reset)
  {
    test_data = 0;
  }
  
  // Receive test pattern from process_b
  static data_t expected = 0;
  // Get data from process_b domain
  uint1_t rd_en = 1;
  // Reset input to fifo
  if(power_on_reset)
  {
    rd_en = 0;
  }
  // Try to read N data elements from the fifo
  process_b_to_process_a_read_t read = process_b_to_process_a_READ_N(rd_en);
  // Did the read go through
  if(rd_en & read.valid)
  {
    for(i = 0; i<DATAS_PER_ITER; i+=1)
    {
      if(read.data[i] != expected)
      {
        // Failed test
        test_failed = 1;
      }
      else
      {
        // Continue checking test pattern
        printf("Process A: Expected %d, got %d\n", expected, read.data[i]);
        expected += 1;
      }
    }
  }
  // Reset statics
  if(power_on_reset)
  {
    test_failed = 0;
    expected = 0;
  }
  power_on_reset = 0;
}

void process_b()
{
  // Drive leds with state, default lit
  static uint1_t power_on_reset = 1;
  static uint1_t test_failed = 0;
  uint1_t led = 1;
  if(test_failed)
  {
    led = 0;
  }
  led2 = led;
  led3 = !power_on_reset;
  
  // Send a test pattern into process_a
  static data_t test_data = 0;
  // Try to write a test data
  data_t wr_data[DATAS_PER_ITER];
  uint32_t i = 0;
  for(i = 0; i<DATAS_PER_ITER; i+=1)
  {
    wr_data[i] = test_data + i;
  }  
  uint1_t wr_en = 1;
  // Reset input to fifo
  if(power_on_reset)
  {
    wr_en = 0;
  }
  process_b_to_process_a_write_t write = process_b_to_process_a_WRITE_N(wr_data, wr_en);
  // Did the write go through?
  if(write.ready)
  {
    // Next test data
    test_data += DATAS_PER_ITER;
  }
  // Reset statics
  if(power_on_reset)
  {
    test_data = 0;
  }
  
  // Receive test pattern from process_a
  static data_t expected = 0;
  // Get data from process_a domain
  uint1_t rd_en = 1;
  // Reset input to fifo
  if(power_on_reset)
  {
    rd_en = 0;
  }
  // Try to read N data elements from the fifo
  process_a_to_process_b_read_t read = process_a_to_process_b_READ_N(rd_en);
  // Did the read go through
  if(rd_en & read.valid)
  {
    for(i = 0; i<DATAS_PER_ITER; i+=1)
    {
      if(read.data[i] != expected)
      {
        // Failed test
        test_failed = 1;
      }
      else
      {
        // Continue checking test pattern
        printf("Process B: Expected %d, got %d\n", expected, read.data[i]);
        expected += 1;
      }
    }
  }
  // Reset statics
  if(power_on_reset)
  {
    test_failed = 0;
    expected = 0;
    printf("Test starting...\n");
  }
  power_on_reset = 0;
}
