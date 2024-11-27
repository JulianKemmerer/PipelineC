#pragma once
// Generated names for FIRs
#include "compiler.h"
#include "fir_names.h"

#define fir_decim_counter_func(fir_name) PPCAT(fir_name,_decim_counter)

#define fir_decim_fir_name(name) PPCAT(name,_fir)

#define fir_decim_out_data_stream_type(decim_name) fir_out_data_stream_type(fir_decim_fir_name(decim_name)) 

#define fir_decim_in_data_stream_type(decim_name) fir_in_data_stream_type(fir_decim_fir_name(decim_name)) 