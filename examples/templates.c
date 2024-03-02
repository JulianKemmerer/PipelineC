#include "templates.h"

template_typename(I)
template_typename(O)
template(O) add_type_template(
  template_t O, template_t I, template(I) x, template(I) y
){
  template(O) rv;
  rv = x + y;
  return rv;
}
#define add_type(out_t, in_t, x, y)\
add_type_template(type(out_t), type(in_t), x, y)

#define MY_TYPE uint32_t
//#pragma MAIN main_type_add
MY_TYPE main_type_add(MY_TYPE x, MY_TYPE y)
{
  return add_type(MY_TYPE, MY_TYPE, x, y);
}


template_typename(T)
typedef struct template2_struct_name(my_struct_t, T, N){
  template(T) field[N];
}template2_struct_name(my_struct_t, T, N);


#pragma MAIN main_struct_type

template_type_inst(template2_struct_name(my_struct_t, uint32_t, 3))

template2_struct_name(my_struct_t, uint32_t, 3) main_struct_type(template2_struct_name(my_struct_t, uint32_t, 3) x){
  return x;
}