// TODO eventually merge into existing i2s.c just choosing i2s source via macros?

// AXIS types and datawidth converters
#include "axi/axis.h"

// Include board media access controller (8b AXIS)
#include "../eth/hardware/xil_temac.c"

// Include logic for parsing/building ethernet frames (32b AXIS)
#include "net/eth_32.c"

// Include the mac address info we want the fpga to have
#include "../eth/hardware/fpga_mac.h"

// Loopback RX to TX with two clock crossing async fifos
//  the FIFOs have valid,ready streaming handshake interfaces
#include "stream/stream.h"

// Function for deserializing axis32 to i2s samples
#include "i2s/i2s_32b.h"
axis_packet_to_type(axis32_to_i2s, 32, i2s_sample_in_mem_t)

// Also expose direct stream wires of samples from I2S RX
// for ex. right into FFT hardware
stream(i2s_samples_t) i2s_rx_samples_monitor_stream;

// Include types for axi shared bus axi_shared_bus_t
#include "axi/axi_shared_bus.h"
// Globally visible AXI bus for this module
axi_shared_bus_t_dev_to_host_t i2s_axi_host_from_dev;
axi_shared_bus_t_host_to_dev_t i2s_axi_host_to_dev;

// Globally visible fifo as input port for I2S RX desc to be written
GLOBAL_STREAM_FIFO(axi_descriptor_t, i2s_rx_desc_to_write_fifo, 16)

// Expose external port FIFO wires for reading RX sample descriptors
GLOBAL_STREAM_FIFO(axi_descriptor_t, i2s_rx_descriptors_monitor_fifo, 16)

// Same clock group as Xilinx TEMAC
MAIN_MHZ_GROUP(rx_main, XIL_TEMAC_RX_MHZ, xil_temac_rx)
#pragma FUNC_MARK_DEBUG rx_main
void rx_main()
{
  // Config bits for RX MAC
  xil_rx_to_temac.pause_req = 0; // not pausing data
  xil_rx_to_temac.pause_val = 0;
  xil_rx_to_temac.rx_configuration_vector = 0;
  xil_rx_to_temac.rx_configuration_vector |= ((uint32_t)1<<1); // RX enable
  xil_rx_to_temac.rx_configuration_vector |= ((uint32_t)1<<12); // 100Mb/s
  // TODO stats+reset+enable and overflow indicator

  // The stream of data from the RX MAC
  stream(axis8_t) mac_axis_rx = xil_temac_to_rx.rx_axis_mac;
  
  // Convert axis8 to axis32
  // Signal always ready, overflow occurs in eth_32_rx 
  //(TEMAC doesnt have mac axis ready flow control)
  // TODO remove old axis8_to_axis32 since have eth_8_rx now
  axis8_to_axis32_t to_axis32 = axis8_to_axis32(mac_axis_rx, 1);
  stream(axis32_t) axis_rx = to_axis32.axis_out;
  
	// Receive the ETH frame
  uint1_t eth_rx_out_ready = 1; // No flow control, overflows
  // The rx module
	eth_32_rx_t eth_rx = eth_32_rx(axis_rx, eth_rx_out_ready);
  eth32_frame_t frame = eth_rx.frame;
  
  // Filter out all but matching destination mac frames
  uint1_t mac_match = frame.header.dst_mac == FPGA_MAC;
  frame.payload.valid &= mac_match;

  // Limit length of frame payload to one struct in size
  // (chop off padding for eth min frame size)
  axis32_max_len_limiter_t limiter = axis32_max_len_limiter(
    sizeof(i2s_sample_in_mem_t),
    frame.payload,
    1 // No flow control, overflows
  );
  
  // Received packet (samples) written to AXI mem
  stream(uint32_t) rx_u32_stream;
  rx_u32_stream.data = uint8_array4_le(limiter.out_stream.data.tdata);
  rx_u32_stream.valid = limiter.out_stream.valid;
  axi_stream_to_writes_t to_axi_wr = u32_stream_to_axi_writes(
    i2s_rx_desc_to_write_fifo_out, // Input stream of descriptors to write
    rx_u32_stream, // Input data stream to write (from I2S MAC)
    i2s_rx_descriptors_monitor_fifo_in_ready, // Ready for output stream of descriptors written
    i2s_axi_host_from_dev.write // Inputs for write side of AXI bus
  );
  i2s_rx_desc_to_write_fifo_out_ready = to_axi_wr.ready_for_descriptors_in;
  // No flow control feedback for eth rx, overflows = to_axi_wr.ready_for_data_stream;
  i2s_rx_descriptors_monitor_fifo_in = to_axi_wr.descriptors_out_stream; // Output stream of written descriptors
  i2s_axi_host_to_dev.write = to_axi_wr.to_dev; // Outputs for write side of AXI bus

  // TEMP DEBUG
  static stream(axis32_t) debug_axis;
  debug_axis = limiter.out_stream;
  static uint1_t debug_axis_ready;
  debug_axis_ready = to_axi_wr.ready_for_data_stream;
  
  // Deserialize axis32 into i2s samples, always ready, overflows
  axis32_to_i2s_t to_i2s = axis32_to_i2s(
    limiter.out_stream,
    1
  );

  // External stream port for samples
  i2s_rx_samples_monitor_stream.data = i2s_samples_from_mem(to_i2s.data);
  i2s_rx_samples_monitor_stream.valid = to_i2s.valid;  
}

// Same clock group as Xilinx TEMAC
MAIN_MHZ_GROUP(tx_main, XIL_TEMAC_TX_MHZ, xil_temac_tx)
#pragma FUNC_WIRES tx_main
void tx_main()
{
  // Config bits for TX MAC
  xil_tx_to_temac.tx_ifg_delay = 0; // no gap between frames
  xil_tx_to_temac.tx_configuration_vector = 0;
  xil_tx_to_temac.tx_configuration_vector |= ((uint32_t)1<<1); // TX enable
  xil_tx_to_temac.tx_configuration_vector |= ((uint32_t)1<<12); // 100Mb/s  
  // TODO stats+reset+enable

  // No TX for now...
}
