// AXI buses as needed by user memory mappings
// Include code for Xilinx DDR AXI shared resource bus as frame buffer example
// Declares AXI shared resource bus wires
//   host_clk_to_dev(axi_xil_mem) and dev_to_host_clk(axi_xil_mem)
#define AXI_RAM_MODE_DDR // Configure frame buffer to use Xilinx AXI DDR RAM (not bram)
#include "../../frame_buffers/hardware/dual_frame_buffer.c"

// I2S RX + TX code
#include "../../i2s/hardware/i2s_axi.c"

// Hardware for doing the full FFT
#include "../../fft/hardware/fft.c"
