// Use the switches to control LED blink rate

#include "uintN_t.h"

// Each main function is a clock domain
// Only one clock in the design for now 'sys_clk' @ 100MHz
#pragma MAIN_MHZ sys_clk_main 100.0
#pragma PART "xc7a35ticsg324-1l" // xc7a35ticsg324-1l = Arty, xcvu9p-flgb2104-2-i = AWS F1

// Make structs that wrap up the inputs and outputs
typedef struct sys_clk_main_inputs_t
{
	// The switches
	uint4_t sw;
} sys_clk_main_inputs_t;
typedef struct sys_clk_main_outputs_t
{
	// The LEDs
	uint1_t led[4];
} sys_clk_main_outputs_t;

// Blinking means turn on LED for some amount of time, and then turn off
// How much time?
#define BLINK_CLK_CYCLES 10000000
// The switch value, ex. sw[3:0] = 0b1101 = 13
// multiplies the above constant to determine actual blink rate
// Ex. 10000000*13 = 130000000 cycles, 100MHz = 10ns per clock, 130000000 * 10ns = 1.3 sec

// We need to count up to whatever sw*BLINK_CLK_CYCLES equals
uint28_t counter; // Inits to zero
// And we need to remember if the LEDs are on or not - so we know what to do next
uint1_t leds_on;

// The sys_clk_main function
sys_clk_main_outputs_t sys_clk_main(sys_clk_main_inputs_t inputs)
{
    // Do what counters do, increment
    counter = counter + 1;

    // If the counter equals or greater then
    // time to toggle the led and reset counter
    if(counter >= (inputs.sw * BLINK_CLK_CYCLES))
    {
        leds_on = !leds_on;
        counter = 0;
    }

    // Drive output leds (all 4)
    sys_clk_main_outputs_t outputs;
    outputs.led[0] = leds_on;
    outputs.led[1] = leds_on;
    outputs.led[2] = leds_on;
    outputs.led[3] = leds_on;

    return outputs;
}
