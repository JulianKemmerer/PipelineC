#pragma once

#define ARRAY_COPY(dest,src,n)\
uint32_t ARRAY_COPY_i; \
for(ARRAY_COPY_i=0;ARRAY_COPY_i<n;ARRAY_COPY_i+=1) \
{ \
  dest[ARRAY_COPY_i] = src[ARRAY_COPY_i]; \
}

#define ARRAY_SET(dest,val,n)\
uint32_t ARRAY_SET_i; \
for(ARRAY_SET_i=0;ARRAY_SET_i<n;ARRAY_SET_i+=1) \
{ \
  dest[ARRAY_SET_i] = val; \
}

#define ARRAY_REV(type_t, array, SIZE)\
uint32_t ARRAY_REV_i; \
type_t ARRAY_REV_temp_##type_t[SIZE] = array; \
for(ARRAY_REV_i=0;ARRAY_REV_i<SIZE;ARRAY_REV_i+=1) \
{ \
  array[ARRAY_REV_i] = ARRAY_REV_temp_##type_t[SIZE-ARRAY_REV_i-1]; \
}

#define ARRAY_SHIFT_DOWN(array,SIZE,AMOUNT)\
uint32_t ARRAY_SHIFT_DOWN_i; \
for(ARRAY_SHIFT_DOWN_i=AMOUNT;ARRAY_SHIFT_DOWN_i<SIZE;ARRAY_SHIFT_DOWN_i+=1) \
{ \
  array[ARRAY_SHIFT_DOWN_i-AMOUNT] = array[ARRAY_SHIFT_DOWN_i]; \
}

#define ARRAY_SHIFT_UP(array,SIZE,AMOUNT)\
uint32_t ARRAY_SHIFT_UP_i; \
for(ARRAY_SHIFT_UP_i=SIZE-1; ARRAY_SHIFT_UP_i>=AMOUNT;ARRAY_SHIFT_UP_i-=1) \
{ \
  array[ARRAY_SHIFT_UP_i] = array[ARRAY_SHIFT_UP_i-AMOUNT]; \
}

#define ARRAY_SHIFT_INTO_TOP(dst_array,SIZE,src_array,IN_SIZE)\
ARRAY_SHIFT_DOWN(dst_array,SIZE,IN_SIZE)\
uint32_t ARRAY_SHIFT_INTO_TOP_i; \
for(ARRAY_SHIFT_INTO_TOP_i=0;ARRAY_SHIFT_INTO_TOP_i<IN_SIZE;ARRAY_SHIFT_INTO_TOP_i+=1) \
{ \
  dst_array[SIZE-IN_SIZE+ARRAY_SHIFT_INTO_TOP_i] = src_array[ARRAY_SHIFT_INTO_TOP_i]; \
}

#define ARRAY_1SHIFT_INTO_TOP(array,SIZE,in_elem)\
ARRAY_SHIFT_DOWN(array,SIZE,1)\
array[SIZE-1] = in_elem;

#define ARRAY_1ROT_DOWN(type_t, array, SIZE)\
/* Save bot element */ \
type_t ARRAY_1ROT_DOWN_##type_t##_temp = array[0]; \
/* Do shift and insert */ \
ARRAY_1SHIFT_INTO_TOP(array, SIZE, ARRAY_1ROT_DOWN_##type_t##_temp)

#define ARRAY_SHIFT_INTO_BOTTOM(dst_array,SIZE,src_array,IN_SIZE)\
ARRAY_SHIFT_UP(dst_array,SIZE,IN_SIZE)\
uint32_t ARRAY_SHIFT_INTO_BOTTOM_i; \
for(ARRAY_SHIFT_INTO_BOTTOM_i=0;ARRAY_SHIFT_INTO_BOTTOM_i<IN_SIZE;ARRAY_SHIFT_INTO_BOTTOM_i+=1) \
{ \
  dst_array[ARRAY_SHIFT_INTO_BOTTOM_i] = src_array[ARRAY_SHIFT_INTO_BOTTOM_i]; \
}

#define ARRAY_1SHIFT_INTO_BOTTOM(array,SIZE,in_elem)\
ARRAY_SHIFT_UP(array,SIZE,1)\
array[0] = in_elem;

#define ARRAY_1ROT_UP(type_t, array, SIZE) \
/* Save top element */ \
type_t ARRAY_1ROT_UP_##type_t##_temp = array[SIZE-1]; \
/* Do shift and insert */ \
ARRAY_1SHIFT_INTO_BOTTOM(array, SIZE, ARRAY_1ROT_UP_##type_t##_temp)

// TODO rename the uint to array funcs with some kind of endianess indicator?

#define UINT_TO_BIT_ARRAY(bit_array,BIT_WIDTH,uint_val)\
uint32_t UINT_TO_ARRAY_i; \
for(UINT_TO_ARRAY_i=0;UINT_TO_ARRAY_i<BIT_WIDTH;UINT_TO_ARRAY_i+=1) \
{ \
  bit_array[UINT_TO_ARRAY_i] = uint_val >> UINT_TO_ARRAY_i; \
}

#define UINT_TO_BYTE_ARRAY(byte_array,BYTE_WIDTH,uint_val)\
uint32_t UINT_TO_BYTE_ARRAY_i; \
for(UINT_TO_BYTE_ARRAY_i=0;UINT_TO_BYTE_ARRAY_i<BYTE_WIDTH;UINT_TO_BYTE_ARRAY_i+=1) \
{ \
  byte_array[UINT_TO_BYTE_ARRAY_i] = uint_val >> (UINT_TO_BYTE_ARRAY_i*8); \
}

// Use arrays for delays/shift regs
#define DELAY_ASSIGN(type_t, out_var, in_var, LATENCY)\
static type_t out_var##_delay_regs[LATENCY];\
type_t in_var##_into_delay = in_var;\
out_var = out_var##_delay_regs[LATENCY-1];\
ARRAY_SHIFT_UP(out_var##_delay_regs, LATENCY, 1)\
out_var##_delay_regs[0] = in_var##_into_delay;
//
#define DELAY_VAR(type_t, var, LATENCY)\
DELAY_ASSIGN(type_t, var, var, LATENCY)
//
#define DELAY_ARRAY_ASSIGN(elem_t, ARRAY_SIZE, out_var, in_var, LATENCY)\
static elem_t out_var##_delay_regs[LATENCY][ARRAY_SIZE];\
elem_t in_var##_into_delay[ARRAY_SIZE];\
in_var##_into_delay = in_var;\
out_var = out_var##_delay_regs[LATENCY-1];\
ARRAY_SHIFT_UP(out_var##_delay_regs, LATENCY, 1)\
out_var##_delay_regs[0] = in_var##_into_delay;
//
#define DELAY_ARRAY(elem_t, ARRAY_SIZE, var, LATENCY)\
DELAY_ARRAY_ASSIGN(elem_t, ARRAY_SIZE, var, var, LATENCY)

// Helper for some repeated IO reg code dealing with arrays
#define ARRAY_IN_REG(elem_t, ARRAY_SIZE, out_var, in_var)\
static elem_t in_var##_input_reg[ARRAY_SIZE];\
elem_t in_var##_array_in_reg_copy[ARRAY_SIZE];\
in_var##_array_in_reg_copy = in_var;\
out_var = in_var##_input_reg;\
in_var##_input_reg = in_var##_array_in_reg_copy;
//
#define ARRAY_OUT_REG(elem_t, ARRAY_SIZE, out_var, in_var)\
static elem_t out_var##_output_reg[ARRAY_SIZE];\
out_var = out_var##_output_reg;\
out_var##_output_reg = in_var;
