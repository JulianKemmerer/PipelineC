#pragma once
#include "compiler.h"

// Functions for global 'wires'
// These are really clock crossing macros, 
// but a clock crossing between the same clock domain is just a wire
// so hide the ugly ratio between clock domains auto gen array struct stuff

// TODO wacky syntax for dynamic #include that might not work with current compiler passes?
/*
https://stackoverflow.com/questions/266501/macro-definition-containing-include-directive
Realise that preprocessor directives won't do anything inside a macro, 
* however they WILL do something in a file. So, you can stick a 
* block of code you want to mutate into a file, thinking of it like a 
* macro definition (with pieces that can be altered by other macros),
*  and then #include this pseudo-macro file in various places 
* (make sure it has no include guards!). It doesn't behave exactly 
* like a macro would, but it can achieve some pretty macro-like results, 
* since #include basically just dumps the contents of one file into another.
*/
/*
//THIS DOESNT WORK \/ ?
#define __arrayn_header(x) #x
#define _arrayn_header(x) __arrayn_header(x##_array_N_t.h)
#define arrayn_header(x) _arrayn_header(x)

#define __clkcross_header(x) #x
#define _clkcross_header(x) __clkcross_header(x##_clock_crossing.h)
#define clkcross_header(x) _clkcross_header(x)

#define WIRE(type, clk_cross_wire_name) \
type clk_cross_wire_name; \
#include arrayn_header(type) \
#include clkcross_header(clk_cross_wire_name)
*/

// Read from a global clock cross same clock domain wire
#define WIRE_READ(type, lhs, clk_cross_name) \
type##_array_1_t clk_cross_name##_clk_cross_read_array = clk_cross_name##_READ(); \
lhs = clk_cross_name##_clk_cross_read_array.data[0];

// Write to a global clock cross same clock domain wire
#define WIRE_WRITE(type, clk_cross_name, rhs) \
type##_array_1_t clk_cross_name##_clk_cross_write_array; \
clk_cross_name##_clk_cross_write_array.data[0] = rhs; \
clk_cross_name##_WRITE(clk_cross_name##_clk_cross_write_array);


// Use global wires to connect up a new main func instance

#define GLOBAL_WIRES_FUNC_DECL(inst_name, out_type, func_name, in_type)\
/* Global wires connected to instance */ \
in_type inst_name##_in; \
out_type inst_name##_out;

// TODO DO NOT REQUIRE TWO MACROS with hack clock crossing gen headers included

#define GLOBAL_WIRES_FUNC_IMPL(inst_name, out_type, func_name, in_type) \
MAIN(inst_name) \
void inst_name() \
{ \
  /* Read inputs*/ \
  in_type input; \
  WIRE_READ(in_type, input, inst_name##_in) \
  /* Pipelined my_func instance*/ \
  out_type output = func_name(input); \
  /* Write outputs*/ \
  WIRE_WRITE(out_type, inst_name##_out, output) \
} \
/* Wrapper helper funcs around corresponding user READ AND WRITE*/ \
void inst_name##_WRITE(in_type input) \
{ \
  WIRE_WRITE(in_type, inst_name##_in, input) \
} \
out_type inst_name##_READ() \
{ \
  out_type output; \
  WIRE_READ(out_type, output, inst_name##_out) \
  return output; \
} \
/* TODO READ_N , WRITE_N for wider clock ratios*/


/*TODO
#define GLOBAL_WIRES_FUNC(inst_name, out_type, func_name, in_type) \
GLOBAL_WIRES_FUNC_DECL(inst_name, out_type, func_name, in_type) \
#pragma CLOCK_CROSSING inst_name##in
#pragma CLOCK_CROSSING inst_name##out
GLOBAL_WIRES_FUNC_IMPL(inst_name, out_type, func_name, in_type) \
*/


// TODO Do reverse of macro taking global wires and creating wrapper function so user gets can specify easy main()

