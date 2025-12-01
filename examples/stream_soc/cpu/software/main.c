#include <stdint.h>
#include <stdlib.h> 

// TODO organize includes
#include "../../fft/software/fft_types.h"
#include "../../power/software/power.h"
#include "../../fft/software/draw.h"
// Not doing FFT in software right now but could...
//#include "../fft/software/fft.c"
#include "mem_map.h"
// TODO how to organize the funcs in these headers?
#include "../../i2s/software/i2s.h"
#include "../../power/software/power_read.h"
#include "../../cam/ov2640/software/ov2640.h"

void main() {
  // Initialize OV2640 camera over SCCB
  ov2640_cam_init();

  // Clear screen to black
  drawRect(0, 0, FRAME_WIDTH, FRAME_HEIGHT, 0, FB0);

  // Configure chunks of I2S samples to read
  uint32_t i2s_addr = I2S_BUFFS_ADDR;
  for(uint32_t i = 0; i < I2S_N_DESC; i++)
  {
    i2s_rx_enq_write((i2s_sample_in_mem_t*)i2s_addr, NFFT);
    i2s_addr += sizeof(i2s_sample_in_mem_t)*NFFT;
  }

  // Configure power spectrum result AXIS sink to write to AXI DDR at specific address
  fft_config_power_result((fft_data_t*)POWER_OUT_ADDR, NFFT);

  while(1){
    // Read i2s samples (in DDR3 off chip)
    i2s_sample_in_mem_t* samples_in_dram = NULL;
    int n_samples = 0;
    if(i2s_try_read(&samples_in_dram, &n_samples)){
      mm_regs->ctrl.led = (1<<0);

      // Time domain waveform across top two thirds of display
      draw_waveform(FRAME_WIDTH, (FRAME_HEIGHT*2)/3, 2, samples_in_dram, n_samples, FB0);

      mm_regs->ctrl.led = (1<<1);

      // Enqueue the buffer to be used for future rx samples writes
      i2s_rx_enq_write(samples_in_dram, n_samples);
    }

    mm_regs->ctrl.led = 0;

    // Read power result (in DDR3 off chip mem)
    fft_data_t* power_out_in_dram;
    if(fft_try_read_power_result(&power_out_in_dram, &n_samples)){
      mm_regs->ctrl.led = (1<<2);

      // Screen coloring result
      draw_spectrum(FRAME_WIDTH, FRAME_HEIGHT, power_out_in_dram, FB0);

      mm_regs->ctrl.led = (1<<3);

      // Confgure next power result output buffer at same place as current
      fft_config_power_result((fft_data_t*)power_out_in_dram, n_samples); // Or (fft_data_t*)POWER_OUT_ADDR)...
    }
    
    mm_regs->ctrl.led = 0;
  }
}
