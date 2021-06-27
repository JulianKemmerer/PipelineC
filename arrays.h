
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

#define ARRAY_SHIFT_INTO_BOTTOM(dst_array,SIZE,src_array,IN_SIZE)\
ARRAY_SHIFT_UP(dst_array,SIZE,IN_SIZE)\
uint32_t ARRAY_SHIFT_INTO_BOTTOM_i; \
for(ARRAY_SHIFT_INTO_BOTTOM_i=0;ARRAY_SHIFT_INTO_BOTTOM_i<IN_SIZE;ARRAY_SHIFT_INTO_BOTTOM_i+=1) \
{ \
  dst_array[ARRAY_SHIFT_INTO_BOTTOM_i] = src_array[ARRAY_SHIFT_INTO_BOTTOM_i]; \
}

// TODO rename - not always bits dummy
#define ARRAY_SHIFT_BIT_INTO_BOTTOM(array,SIZE,in_bit)\
ARRAY_SHIFT_UP(array,SIZE,1)\
array[0] = in_bit;

#define UINT_TO_BIT_ARRAY(bit_array,BIT_WIDTH,uint_val)\
uint32_t UINT_TO_ARRAY_i; \
for(UINT_TO_ARRAY_i=0;UINT_TO_ARRAY_i<BIT_WIDTH;UINT_TO_ARRAY_i+=1) \
{ \
  bit_array[UINT_TO_ARRAY_i] = uint_val >> UINT_TO_ARRAY_i; \
}
