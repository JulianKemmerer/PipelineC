#include "compiler.h" // PRAGMA_MESSAGE
#include "wire.h"     // WIRE READ+WRITE
#include "uintN_t.h"  // uintN_t types for any N

// Install+configure synthesis tool then specify part here
// #pragma PART "xc7a35ticsg324-1l" 

// TO BE "debug_wire.h" maybe
#define DEBUG_OUTPUT_DECL(type_t, name) \
type_t name##_DEBUG; \
PRAGMA_MESSAGE(MAIN name##_DEBUG_OUTPUT_MAIN) \
type_t name##_DEBUG_OUTPUT_MAIN() \
{ \
  type_t rv; \
  WIRE_READ(type_t, rv, name##_DEBUG) \
  return rv; \
} \
void name(type_t val) \
{ \
  WIRE_WRITE(type_t, name##_DEBUG, val) \
}

#define DEBUG_INPUT_DECL(type_t, name) \
type_t name##_DEBUG; \
PRAGMA_MESSAGE(MAIN name##_DEBUG_INPUT_MAIN) \
void name##_DEBUG_INPUT_MAIN(type_t val) \
{ \
  WIRE_WRITE(type_t, name##_DEBUG, val)\
} \
type_t name() \
{ \
  type_t rv; \
  WIRE_READ(type_t, rv, name##_DEBUG) \
  return rv; \
}

#include "clock_crossing/counter_debug_DEBUG.h"
DEBUG_OUTPUT_DECL(uint25_t, counter_debug)

#include "clock_crossing/led_debug_DEBUG.h"
DEBUG_OUTPUT_DECL(uint1_t, led_debug)

//#include "clock_crossing/inc_debug_DEBUG.h"
//DEBUG_INPUT_DECL(uint4_t, inc_debug)

uint25_t counter;

// LED on off state
uint1_t led;

// 'Called'/'Executing' every 30ns (33.33MHz)
#pragma MAIN_MHZ blink 33.33
uint1_t blink()
{
  counter_debug(counter);
  led_debug(led);
  
  // If reached 1 second
  if(counter==(3-1))
  {
    // Toggle led
    led = !led;
    // Reset counter
    counter = 0;
  }
  else
  {
    //uint4_t inc = inc_debug();
    //counter += inc;
    counter += 1; // one 30ns increment
  }  
  
  return led;
}





