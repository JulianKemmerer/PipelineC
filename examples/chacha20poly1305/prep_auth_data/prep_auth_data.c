#include "prep_auth_data/prep_auth_data.h"

stream(axis128_t) prep_auth_data_axis_in; // input
uint1_t prep_auth_data_axis_in_ready; // output
stream(axis128_t) prep_auth_data_axis_out; // output
uint1_t prep_auth_data_axis_out_ready; // input

#pragma MAIN prep_auth_data
void prep_auth_data()
{
  #warning "TODO prep auth data"
  // pass through for now
  prep_auth_data_axis_out = prep_auth_data_axis_in;
  prep_auth_data_axis_in_ready = prep_auth_data_axis_out_ready;
}