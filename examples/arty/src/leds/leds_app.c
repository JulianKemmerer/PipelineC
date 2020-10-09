// Include leds module with globally visible port/wire
#include "leds.c"

// This app blinks the leds
#pragma MAIN_MHZ app 100.0
// Blinking means turn on LED for some amount of time, and then turn off
// How much time?
#define BLINK_CLK_CYCLES 100000000
// Ex. 100000000 cycles, 100MHz = 10ns per clock, = 1.0 sec
uint25_t counter_reg; // Inits to zero
// Remember if the LEDs are on or not
uint4_t leds_on_reg;
void app()
{
  // Drive the leds from register state
  WIRE_WRITE(uint4_t, leds, leds_on_reg) // leds = leds_on_reg;
  
  // Do what counters do, increment
  counter_reg += 1;
  // If the counter equals or greater then
  // time to toggle the led and reset counter
  if(counter_reg >= BLINK_CLK_CYCLES)
  {
      // Toggle leds
      if(leds_on_reg==0){
        leds_on_reg = 0xF; // All 4 leds
      }else{
        leds_on_reg = 0;
      }
      // Reset counter
      counter_reg = 0;
  }
}
