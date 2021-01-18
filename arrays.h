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

