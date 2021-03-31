
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

// TODO make these not need 'i' and define extra ARRAY_SHIFT_DOWN_i in-line
#define ARRAY_SHIFT_DOWN(a,SIZE,AMOUNT,i)\
for(i=AMOUNT;i<SIZE;i+=1) \
{ \
  a[i-AMOUNT] = a[i]; \
}

#define ARRAY_SHIFT_UP(a,SIZE,AMOUNT,i)\
for(i=SIZE-1; i>=AMOUNT;i-=1) \
{ \
  a[i] = a[i-AMOUNT]; \
}

#define ARRAY_SHIFT_INTO_TOP(a,SIZE,in_data,IN_SIZE,i)\
ARRAY_SHIFT_DOWN(a,SIZE,IN_SIZE,i)\
for(i=0;i<IN_SIZE;i+=1) \
{ \
  a[SIZE-IN_SIZE+i] = in_data[i]; \
}

#define ARRAY_SHIFT_INTO_BOTTOM(a,SIZE,in_data,IN_SIZE,i)\
ARRAY_SHIFT_UP(a,SIZE,IN_SIZE,i)\
for(i=0;i<IN_SIZE;i+=1) \
{ \
  a[i] = in_data[i]; \
}

