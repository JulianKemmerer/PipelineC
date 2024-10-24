// For test bench to not need multiple clocks, 
// keep simple and define both clock the same
#define FFT_CLK_2X_MHZ 100
#define FFT_CLK_MHZ 100
#include "fft_2pt_2x_clk.c"

#pragma MAIN tb_i2s_input
void tb_i2s_input(){
  // Drive counters as i2s samples
  static uint32_t counter;
  samples_fifo_in.data.l = counter;
  samples_fifo_in.data.r = counter;
  samples_fifo_in.valid = 1;
  if(samples_fifo_in_ready){
    printf("Inputing sample %d\n", counter);
    counter += 1;
  }
}

#pragma MAIN tb_cpu_output
void tb_cpu_output(){
  // Drain CPU output fifo
  output_fifo_out_ready = 1;
  if(output_fifo_out.valid){
    printf(
      "Output value real %d imag\n", 
      output_fifo_out.data.real, 
      output_fifo_out.data.imag
    );
  }
}
