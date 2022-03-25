// Unlike async_clock_crossing.c this example marks the wire between the two domains
// as being ASYNC_WIRE. This mean no clock crossing checking/buffering is done.
// Use with caution.

#include "compiler.h"
#include "wire.h"

#pragma MAIN_MHZ fast 166.66
#pragma MAIN_MHZ slow 25.0

#include "uintN_t.h"

// Demo/dummy test since had to do specific useful things with ASYNC_WIREs
// Make a counter in each domain, sampling it in the other.

uint32_t fast_to_slow; 
#include "clock_crossing/fast_to_slow.h" // Auto generated
#pragma ASYNC_WIRE fast_to_slow

uint32_t slow_to_fast;
#include "clock_crossing/slow_to_fast.h" // Auto generated
#pragma ASYNC_WIRE slow_to_fast

uint32_t fast()
{
  // Count using value from other domain as increment
  static uint32_t counter = 0;
  uint32_t rv = counter;

  // Receive test data from other domain
  uint32_t from_slow;
  WIRE_READ(uint32_t, from_slow, slow_to_fast)
  counter += from_slow;

  // Send test data into other domain
  WIRE_WRITE(uint32_t, fast_to_slow, rv)

  return rv; // So doesnt optimize away
}

uint32_t slow()
{
  // Count using value from other domain as increment
  static uint32_t counter = 0;
  uint32_t rv = counter;

  // Receive test data from other domain
  uint32_t from_fast;
  WIRE_READ(uint32_t, from_fast, fast_to_slow)
  counter += from_fast;

  // Send test data into other domain
  WIRE_WRITE(uint32_t, slow_to_fast, rv)

  return rv; // So doesnt optimize away
}
