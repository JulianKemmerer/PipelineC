#pragma once
// Generated names for FIRs
#include "compiler.h"
#include "fir_names.h"

#define fir_interp_insert_n_zeros_func(fir_name) PPCAT(fir_name,_interp_insert_n_zeros)

#define fir_interp_fir_name(name) PPCAT(name,_fir)

#define fir_interp_out_data_stream_type(interp_name) fir_out_data_stream_type(fir_interp_fir_name(interp_name)) 

#define fir_interp_in_data_stream_type(interp_name) fir_in_data_stream_type(fir_interp_fir_name(interp_name)) 