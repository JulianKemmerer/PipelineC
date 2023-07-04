// Send a stream of uint64_t datas across a clock crossing
// In this example the domains are sync integer ratios and 
// so the crossing is implemented with 
// 'volatile' (inserting zeros) de/serializer buffers

#include "compiler.h"
#include "wire.h"
#include "leds/led0_3_ports.c"

#pragma MAIN_MHZ fast 100.0
#pragma MAIN_MHZ slow 25.0

// Stream of uint64_t values
#include "uintN_t.h"
typedef struct uint64_s
{
  uint64_t data;
  uint1_t valid;  
} uint64_s;

volatile uint64_s fast_to_slow;
#include "clock_crossing/fast_to_slow.h" // Auto generated
volatile uint64_s slow_to_fast;
#include "clock_crossing/slow_to_fast.h" // Auto generated

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
  static uint64_t test_data = 0;
  // Incrementing words
  uint64_s to_slow;
  to_slow.data = test_data;
  to_slow.valid = 1;
  test_data += 1;
  // Reset statics and outputs?
  if(reset)
  {
    test_data = 0;
    to_slow.valid = 0;
  }
  // Send data into slow domain
  fast_to_slow_write_t to_slow_array;
  to_slow_array.data[0] = to_slow;
  fast_to_slow_WRITE(to_slow_array);
  
  // Receive test pattern from slow
  static uint64_t expected = 0;
  // Get data from slow domain
  slow_to_fast_read_t from_slow_array = slow_to_fast_READ();
  uint64_s from_slow = from_slow_array.data[0];
  if(from_slow.valid)
  {
    if(from_slow.data != expected)
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
  
  // Send test pattern into fast
  static uint64_t test_data = 0;
  slow_to_fast_write_t to_fast_array;
  uint32_t i;
  for(i=0;i<slow_to_fast_RATIO;i+=1)
  {
    to_fast_array.data[i].data = test_data + i;
    to_fast_array.data[i].valid = 1;
  }
  test_data += slow_to_fast_RATIO;
  // Reset statics and outputs?
  if(reset)
  {
    test_data = 0;
    for(i=0;i<slow_to_fast_RATIO;i+=1)
    {
      to_fast_array.data[i].valid = 0;
    }
  }
  // Send data into fast domain
  slow_to_fast_WRITE(to_fast_array);
  
  // Receive test pattern from fast
  static uint64_t expected = 0;
  // Get datas from fast domain
  fast_to_slow_read_t from_fast_array;
  from_fast_array = fast_to_slow_READ();
  for(i=0;i<fast_to_slow_RATIO;i+=1)
  {
    if(from_fast_array.data[i].valid)
    {
      if(from_fast_array.data[i].data != expected)
      {
        test_failed = 1;
      }
      else
      {
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
