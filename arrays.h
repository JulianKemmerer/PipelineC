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

