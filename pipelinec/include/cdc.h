#pragma once

#define CDC(type, name, num_regs, lhs, rhs) \
static type name##_registers[num_regs];\
uint8_t name##_i;\
lhs = name##_registers[0];\
for(name##_i=0;name##_i<(num_regs-1);name##_i+=1)\
{\
  name##_registers[name##_i] = name##_registers[name##_i+1];\
}\
name##_registers[num_regs-1] = rhs;

#define CDC2(type, name, lhs, rhs) CDC(type, name, 2, lhs, rhs)
