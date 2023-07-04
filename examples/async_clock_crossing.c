// Similar to clock_crossing.c except that instead of 
// data width integer ratioed clock crossing stream,
// this uses same size read and write ports on an async fifo

#include "uintN_t.h"
#include "leds/led0_3_ports.c"

#pragma MAIN_MHZ fast 166.66
#pragma MAIN_MHZ slow 25.0

// Write+read 2 'datas' in/out the fifo at a time
// (port sizes on each side of async fifo)
#define data_t uint8_t
#define DATAS_PER_ITER 2
#define fast_to_slow_WRITE_N fast_to_slow_WRITE_2
#define slow_to_fast_READ_N slow_to_fast_READ_2
#define slow_to_fast_WRITE_N slow_to_fast_WRITE_2
#define fast_to_slow_READ_N fast_to_slow_READ_2

// Fifo depth=4
//data_t fast_to_slow[4]; 
//#include "clock_crossing/fast_to_slow.h" // Auto generated
#include "clock_crossing.h"
ASYNC_CLK_CROSSING_WIDTH_DEPTH(data_t, fast_to_slow, DATAS_PER_ITER, 4)

// Fifo depth=4
//data_t slow_to_fast[4]; 
//#include "clock_crossing/slow_to_fast.h" // Auto generated
ASYNC_CLK_CROSSING_WIDTH_DEPTH(data_t, slow_to_fast, DATAS_PER_ITER, 4)

void fast(uint1_t reset)
{  
  // Drive leds with state, default lit
  static uint1_t test_failed = 0;
  uint1_t led = 1;
  if(test_failed)
  {
    led = 0;
  }
  led0 = led;
  led1 = !reset;
  
  // Send a test pattern into slow
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
  if(reset)
  {
    wr_en = 0;
  }
  fast_to_slow_write_t write = fast_to_slow_WRITE_N(wr_data, wr_en);
  // Did the write go through?
  if(write.ready)
  {
    // Next test data
    test_data += DATAS_PER_ITER;
  }
  // Reset statics
  if(reset)
  {
    test_data = 0;
  }
  
  // Receive test pattern from slow
  static data_t expected = 0;
  // Get data from slow domain
  uint1_t rd_en = 1;
  // Reset input to fifo
  if(reset)
  {
    rd_en = 0;
  }
  // Try to read 1 data element from the fifo
  slow_to_fast_read_t read = slow_to_fast_READ_N(rd_en);
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
        expected += 1;
      }
    }
  }
  // Reset statics
  if(reset)
  {
    test_failed = 0;
    expected = 0;
  }
}

void slow(uint1_t reset)
{
  // Drive leds with state, default lit
  static uint1_t test_failed = 0;
  uint1_t led = 1;
  if(test_failed)
  {
    led = 0;
  }
  led2 = led;
  led3 = !reset;
  
  // Send a test pattern into fast
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
  if(reset)
  {
    wr_en = 0;
  }
  slow_to_fast_write_t write = slow_to_fast_WRITE_N(wr_data, wr_en);
  // Did the write go through?
  if(write.ready)
  {
    // Next test data
    test_data += DATAS_PER_ITER;
  }
  // Reset statics
  if(reset)
  {
    test_data = 0;
  }
  
  // Receive test pattern from fast
  static data_t expected = 0;
  // Get data from fast domain
  uint1_t rd_en = 1;
  // Reset input to fifo
  if(reset)
  {
    rd_en = 0;
  }
  // Try to read 1 data element from the fifo
  fast_to_slow_read_t read = fast_to_slow_READ_N(rd_en);
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
        expected += 1;
      }
    }
  }
  // Reset statics
  if(reset)
  {
    test_failed = 0;
    expected = 0;
  }
}
