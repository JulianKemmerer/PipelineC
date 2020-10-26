// 'App' that use the switches to control LED blink rate
#include "wire.h"     // Macros for reading/writing global wires
#include "uintN_t.h"  // uintN_t types for any N

// Board IO's have their own modules (top level ports done for you)
// that expose virtual, globally visible, ports/signals
#include "leds/leds.c"
#include "switches/switches.c"

// Each main function is a clock domain
// Only one clock in the design for now
#pragma MAIN_MHZ app 100.0

// Blinking means turn on LED for some amount of time, and then turn off
// How much time?
#define BLINK_CLK_CYCLES 10000000
// The switch value, ex. sw[3:0] = 0b1101 = 13
// multiplies the above constant to determine actual blink rate
// Ex. 10000000*13 = 130000000 cycles, 100MHz = 10ns per clock, 130000000 * 10ns = 1.3 sec

// We need to count up to whatever sw*BLINK_CLK_CYCLES equals
uint28_t counter; // Inits to zero
// And we need to remember if the LEDs are on or not - so we know what to do next
uint4_t leds_on;

// The sys_clk_main function
void app()
{
    // Read switches input (i.e. like a function argument)
    uint4_t sw;
    WIRE_READ(uint4_t, sw, switches) // sw (local wire) = switches (global wire)
    
    // Do what counters do, increment
    counter = counter + 1;

    // If the counter equals or greater then
    // time to toggle the leds and reset counter
    if(counter >= (sw * BLINK_CLK_CYCLES))
    {
        leds_on = ~leds_on;
        counter = 0;
    }

    // Drive output leds (all 4) (i.e. like a function return value)
    WIRE_WRITE(uint4_t, leds, leds_on) // leds (global wire) = leds_on (local wire)
}
