
#include "compiler.h"
#include "wire.h"
#include "intN_t.h"
#include "uintN_t.h"

// Global variable value at the end of the write function's execution/return
// is what read functions see at/triggers the start of their execution
// Maybe add pragma to wire directly to reg output/delayed a cycle instead?
int32_t the_global = 0;
// All reads and writes must be same clock domain
//  or use proper clock crossing mechanisms
//  or marked as as ASYNC_WIRE
#pragma ASYNC_WIRE the_global

void write_func(uint1_t sel)
{
  // Save global
  int32_t temp = the_global;
  // 'Erase it' ~maybe
  if(sel)
  {
    the_global = -1;
    // Do some stuff, could be anything
    int32_t result = temp*temp; // do_some_stuff();
    // Reset global
    the_global = temp;
    // Accum for demo
    the_global += result;
  }
}
#pragma MAIN_MHZ write_main 100.0
void write_main(uint1_t sel)
{
  write_func(sel);
}
/*// Not allowed, get error about ~multiple drivers
#pragma MAIN_MHZ another_write_main 100.0
void another_write_main(uint1_t sel)
{
  write_func(sel);
}*/

uint32_t read_func()
{
  static uint32_t local_counter;
  if(the_global==-1)
  {
    // Never reaches here
    // "inter-clock cycle" variable state from write_main never seen
    local_counter = 0;
  }
  // Count as demo
  local_counter += the_global;
  return local_counter;
}
#pragma MAIN_MHZ read_main 100.0
uint32_t read_main()
{
  return read_func();
}
#pragma MAIN_MHZ another_read_main 100.0
uint32_t another_read_main()
{
  return read_func();
}
// Get error about multiple clocks unless marked ASYNC_WIRE
#pragma MAIN_MHZ not_same_clk_read_main 50.0
uint32_t not_same_clk_read_main()
{
  return read_func();
}