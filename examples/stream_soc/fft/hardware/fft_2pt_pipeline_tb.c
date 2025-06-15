#pragma PART "xc7a100tcsg324-1"
#include "stream/stream.h"
#include "global_func_inst.h"
#include "gcc_test/fft.h"
DECL_STREAM_TYPE(fft_2pt_w_omega_lut_in_t)
DECL_STREAM_TYPE(fft_2pt_out_t)
//DECL_STREAM_TYPE(fft_out_t)

// Global instance of butterfly pipeline with valid ready handshake
GLOBAL_VALID_READY_PIPELINE_INST(fft_2pt_pipeline, fft_2pt_out_t, fft_2pt_w_omega_lut, fft_2pt_w_omega_lut_in_t, 16)


uint16_t rand_lfsr(uint16_t lfsr){
  uint16_t bit = ((lfsr >> 0) ^
        (lfsr >> 2) ^
        (lfsr >> 3) ^
        (lfsr >> 5)) & 1;
  return (lfsr >> 1)  | (bit << 15);
}
  

// Instannce of fft_2pt_fsm connected to FIFOs and butterfly pipeline
#define FFT_CLK_MHZ 100.0
MAIN_MHZ(main_in, FFT_CLK_MHZ)
fft_2pt_out_t main_in(){
  static uint16_t lfsr = 0xACE1;
  static uint32_t in_count;
  static fft_2pt_w_omega_lut_in_t in_reg =
  {
    .s=2,
    .j=1, 
    .t={.real=-511,.imag=0}, 
    .u={.real=-511,.imag=0}
  };
  fft_2pt_pipeline_in.valid = 1; //lfsr(0);
  if(lfsr(0)){ //fft_2pt_pipeline_in.valid){
    fft_2pt_pipeline_in.data = in_reg;
  }else{
    fft_2pt_w_omega_lut_in_t din_null = {0};
    fft_2pt_pipeline_in.data = din_null;
  }
  if(fft_2pt_pipeline_in.valid & fft_2pt_pipeline_in_ready){
    printf("in %d nonzero data %d\n", in_count, lfsr(0));
    /*in_reg.s += 1;
    in_reg.j += 1;
    in_reg.t.real += 1;
    in_reg.t.imag -= 1;
    in_reg.u.real -= 1;
    in_reg.u.imag += 1;*/
    in_count += 1;
  }
  fft_2pt_pipeline_out_ready = 1; // lfsr(1);
  static uint32_t out_count;
  if(fft_2pt_pipeline_out.valid & fft_2pt_pipeline_out_ready)
  {
    printf("out %d: tr %d ti %d ur %d ui %d\n", 
      out_count,
      fft_2pt_pipeline_out.data.t.real,
      fft_2pt_pipeline_out.data.t.imag,
      fft_2pt_pipeline_out.data.u.real,
      fft_2pt_pipeline_out.data.u.imag
    );
    out_count += 1;
  }
  lfsr = rand_lfsr(lfsr);
  return fft_2pt_pipeline_out.data;
}


