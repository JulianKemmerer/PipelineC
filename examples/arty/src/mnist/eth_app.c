#include "compiler.h"
#include "intN_t.h"
#include "uintN_t.h"

// LEDs for signaling overflow
#include "../leds/leds.c"

// AXIS is how to stream data
#include "axi/axis.h"

// Include board media access controller (8b AXIS)
#include "../eth/xil_temac.c"

// Include the mac address info we want the fpga to have
#include "../eth/fpga_mac.h"

// Include logic for parsing ethernet frames from 32b AXIS
#include "net/eth_32.c"

// Some constants related to the neural net
#define NN_CLOCK_MHZ 6.25
#define MNIST_IMAGE_WIDTH 28
#define MNIST_IMAGE_HEIGHT 28
#define MNIST_IMAGE_SIZE MNIST_IMAGE_WIDTH * MNIST_IMAGE_HEIGHT
#define MNIST_LABELS 10
#define pixel_t uint8_t
#define FLOAT_MIN -9999999.0 // Fake but works

// Type for communicating pixel updates to FPGA as input
#include "pixels_update.h"

// Helper functions to convert bytes to/from input type
#include "pixels_update_t_bytes_t.h"

// FIFO to hold ethernet header so can be used for reply address (TODO: dont need)
eth_header_t headers_fifo[2];
#include "clock_crossing/headers_fifo.h"

// Declare function to convert axis32 to input type
axis_to_type(axis_to_input, 32, pixels_update_t)

// FIFO to hold inputs buffered from the TEMAC AXIS stream
pixels_update_t inputs_fifo[16];
#include "clock_crossing/inputs_fifo.h"

// Receive logic
// Same clock group as Xilinx TEMAC, infers clock from group + clock crossings
#pragma MAIN_GROUP rx_main xil_temac_rx 
void rx_main()
{
  // Read wire from RX MAC
  xil_temac_to_rx_t from_mac;
  WIRE_READ(xil_temac_to_rx_t, from_mac, xil_temac_to_rx) // from_mac = xil_temac_to_rx
  // The stream of data from the RX MAC
  axis8_t mac_axis_rx = from_mac.rx_axis_mac;
  
  // TODO stats+reset+enable
  // Light LED on RX overflow
  static uint1_t overflow;
  WIRE_WRITE(uint4_t, leds, overflow)

  // Convert axis8 to axis32
  // Signal always ready, overflow occurs in eth_32_rx 
  //(TEMAC doesnt have mac axis ready flow control)
  axis8_to_axis32_t to_axis32 = axis8_to_axis32(mac_axis_rx, 1);
  axis32_t axis32_rx = to_axis32.axis_out;
  
  // Receive the ETH frame
  // Feedback inputs from later modules
  uint1_t eth_rx_out_ready;
  #pragma FEEDBACK eth_rx_out_ready
  // The rx module
  eth_32_rx_t eth_rx = eth_32_rx(axis32_rx, eth_rx_out_ready);
  eth32_frame_t frame = eth_rx.frame;
  overflow |= eth_rx.overflow;
  
  // Filter out all but matching destination mac frames
  uint8_t FPGA_MAC_BYTES[6];
  FPGA_MAC_BYTES[0] = FPGA_MAC0;
  FPGA_MAC_BYTES[1] = FPGA_MAC1;
  FPGA_MAC_BYTES[2] = FPGA_MAC2;
  FPGA_MAC_BYTES[3] = FPGA_MAC3;
  FPGA_MAC_BYTES[4] = FPGA_MAC4;
  FPGA_MAC_BYTES[5] = FPGA_MAC5;
  uint48_t FPGA_MAC = uint8_array6_be(FPGA_MAC_BYTES); // Network, big endian, byte order
  uint1_t mac_match = frame.header.dst_mac == FPGA_MAC;
  
  // Pass through payload if mac match
  frame.payload.valid &= eth_rx_out_ready & mac_match;
  // Only write into headers fifo if starting a packet
  uint1_t header_wr_en = eth_rx.start_of_packet & eth_rx_out_ready & mac_match;
  
  // Write header into fifo at start of payload
  eth_header_t header_wr_data[1];
  header_wr_data[0] = frame.header;
  headers_fifo_write_t header_write = headers_fifo_WRITE_1(header_wr_data, header_wr_en);
  
  // Data deserializer payload into inputs which writes into fifo
  uint1_t deserializer_output_ready;
  #pragma FEEDBACK deserializer_output_ready
  axis_to_input_t to_input = axis_to_input(frame.payload,deserializer_output_ready);

  // Frame was ready if axis32_to_inputs was ready (header fifo not really used as fifo)
  eth_rx_out_ready = to_input.payload_ready; // & header_write.ready; // FEEDBACK

  // Write inputs into fifo
  pixels_update_t input_wr_data[1];
  input_wr_data[0] = to_input.data;
  inputs_fifo_write_t input_write = inputs_fifo_WRITE_1(input_wr_data, to_input.valid);
  
  // Converter out ready if fifo was ready
  deserializer_output_ready = input_write.ready; // FEEDBACK
  
  // Write wires back into RX MAC
  xil_rx_to_temac_t to_mac;
  // Config bits
  to_mac.pause_req = 0;
  to_mac.pause_val = 0;
  to_mac.rx_configuration_vector = 0;
  to_mac.rx_configuration_vector |= ((uint32_t)1<<1); // RX enable
  to_mac.rx_configuration_vector |= ((uint32_t)1<<12); // 100Mb/s 
  WIRE_WRITE(xil_rx_to_temac_t, xil_rx_to_temac, to_mac) // xil_rx_to_temac = to_mac
}

// A shared single instance main function for the dual port N-pixel wide memory
// With global wires and helper functions for individual ports
// Read port
uint16_t pixel_mem_raddr;
#include "clock_crossing/pixel_mem_raddr.h"
n_pixels_t pixel_mem_rdata;
#include "clock_crossing/pixel_mem_rdata.h"
// Write port
uint16_t pixel_mem_waddr;
#include "clock_crossing/pixel_mem_waddr.h"
n_pixels_t pixel_mem_wdata;
#include "clock_crossing/pixel_mem_wdata.h"
uint1_t pixel_mem_we;
#include "clock_crossing/pixel_mem_we.h"
MAIN_MHZ(shared_pixel_mem, NN_CLOCK_MHZ)
void shared_pixel_mem()
{
    static n_pixels_t pixel[(MNIST_IMAGE_SIZE/N_PIXELS_PER_ITER)];
    // Read port
    uint16_t raddr;
    n_pixels_t rdata;
    // Write port
    uint16_t waddr;
    n_pixels_t wdata;
    uint1_t we;
    WIRE_READ(uint16_t, raddr, pixel_mem_raddr)
    WIRE_READ(uint16_t, waddr, pixel_mem_waddr)
    WIRE_READ(n_pixels_t, wdata, pixel_mem_wdata)
    WIRE_READ(uint1_t, we, pixel_mem_we)
    n_pixels_t rdata = pixel_RAM_DP_RF_0(raddr, waddr, wdata, we); // ROM lookup, built in function template
    WIRE_WRITE(n_pixels_t, pixel_mem_rdata, rdata)
}
void pixel_mem_write(uint16_t addr, n_pixels_t data, uint1_t enable)
{
    WIRE_WRITE(uint16_t, pixel_mem_waddr, addr)
    WIRE_WRITE(n_pixels_t, pixel_mem_wdata, data)
    WIRE_WRITE(uint1_t, pixel_mem_we, enable)
}
n_pixels_t pixel_mem_read(uint16_t addr)
{
    WIRE_WRITE(uint16_t, pixel_mem_raddr, addr)
    n_pixels_t rdata;
    WIRE_READ(n_pixels_t, rdata, pixel_mem_rdata)
    return rdata;
}

// Logic to read from inputs fifo and use the write port to write to pixel memory
void pixel_writer()
{
    // Inf loop
    while(1)
    {
        // Wait to get pixels update from FIFO
        pixels_update_t pixels_update;
        uint1_t got_pixels_update = 0;
        while(!got_pixels_update)
        {
            // Read incoming inputs from rx_main
            inputs_fifo_read_t input_read = inputs_fifo_READ_1(1); 
            pixels_update = input_read.data[0]; 
            got_pixels_update = input_read.valid;
            __clk();   
        }

        // Then write pixel update
        uint16_t addr = pixels_update.addr;
        n_pixels_t n_pixels;
        n_pixels.data = pixels_update.pixels;
        // Write the pixels
        pixel_mem_write(addr, n_pixels, 1);
        __clk();
    }
}
// Derived fsm from func
#include "pixel_writer_FSM.h"
// Wrap up FSM as top level
MAIN_MHZ(pixel_writer_FSM_wrapper, NN_CLOCK_MHZ)
void pixel_writer_FSM_wrapper()
{
  pixel_writer_INPUT_t i;
  i.input_valid = 1;
  i.output_ready = 1;
  pixel_writer_OUTPUT_t o = pixel_writer_FSM(i);
}

// Output response of prediciton
#include "pred_resp.h"

// Helper functions to convert bytes to/from output type
#include "pred_resp_t_bytes_t.h"

// Declare function to convert the output type to axis32 
type_to_axis(output_to_axis, pred_resp_t, 32) // macro

// Outputs fifo of prediction responses
pred_resp_t outputs_fifo[16];
#include "clock_crossing/outputs_fifo.h"

// Transmit logic
#pragma MAIN_GROUP tx_main xil_temac_tx // Same clock group as Xilinx TEMAC, infers clock from group + clock crossings
void tx_main()
{
  // Read wires from TX MAC
  xil_temac_to_tx_t from_mac;
  WIRE_READ(xil_temac_to_tx_t, from_mac, xil_temac_to_tx) // from_mac = xil_temac_to_tx
  uint1_t mac_ready = from_mac.tx_axis_mac_ready;
  
  // TODO stats+reset+enable
  
  // Read outputs from fifo
  uint1_t outputs_fifo_read_en;
  #pragma FEEDBACK outputs_fifo_read_en
  outputs_fifo_read_t output_read = outputs_fifo_READ_1(outputs_fifo_read_en);
  
  // Serialize outputs to axis
  uint1_t serializer_output_ready;
  #pragma FEEDBACK serializer_output_ready
  output_to_axis_t to_axis = output_to_axis(output_read.data[0], output_read.valid, serializer_output_ready);
  // Read outputs from fifo if serializer is ready
  outputs_fifo_read_en = to_axis.input_data_ready; // FEEDBACK
  
  // Use header from fifo output, but dont read it out ever (not used as fifo)
  uint1_t header_read_en = 0;
  //#pragma FEEDBACK header_read_en
  headers_fifo_read_t header_read = headers_fifo_READ_1(header_read_en);  
  
	// Wire up the ETH frame to send
  eth32_frame_t frame;
  // Header matches what was sent other than SRC+DST macs
  frame.header = header_read.data[0];
  uint8_t FPGA_MAC_BYTES[6];
  FPGA_MAC_BYTES[0] = FPGA_MAC0;
  FPGA_MAC_BYTES[1] = FPGA_MAC1;
  FPGA_MAC_BYTES[2] = FPGA_MAC2;
  FPGA_MAC_BYTES[3] = FPGA_MAC3;
  FPGA_MAC_BYTES[4] = FPGA_MAC4;
  FPGA_MAC_BYTES[5] = FPGA_MAC5;
  uint48_t FPGA_MAC = uint8_array6_be(FPGA_MAC_BYTES); // Network, big endian, byte order
  frame.header.dst_mac = frame.header.src_mac; // Send back to where came from
  frame.header.src_mac = FPGA_MAC; // From FPGA
  // Header and payload need to be valid to send
  frame.payload = to_axis.payload;
  frame.payload.valid = to_axis.payload.valid & header_read.valid;
  
  // The tx module
  uint1_t eth_tx_out_ready;
  #pragma FEEDBACK eth_tx_out_ready
  eth_32_tx_t eth_tx = eth_32_tx(frame, eth_tx_out_ready);
  axis32_t axis_tx = eth_tx.mac_axis;
  
  // Serializer axis output is ready if tx module is ready
  serializer_output_ready = eth_tx.frame_ready & frame.payload.valid; // FEEDBACK
  
  // Read header if was ready, dropping on floor, at end of packet
  //header_read_en = eth_tx.frame_ready & frame.payload.last & frame.payload.valid; // FEEDBACK
    
	// Convert axis32 to axis8
  axis32_to_axis8_t to_axis8 = axis32_to_axis8(axis_tx, mac_ready);
  axis8_t mac_axis_tx = to_axis8.axis_out;
  
  // Tx module ready if axis width converter ready
  eth_tx_out_ready = to_axis8.axis_in_ready; // FEEDBACK
  
  // Write wires back into TX MAC 
  xil_tx_to_temac_t to_mac;
  to_mac.tx_axis_mac = mac_axis_tx;
  // Config bits
  to_mac.tx_ifg_delay = 0;
  to_mac.tx_configuration_vector = 0;
  to_mac.tx_configuration_vector |= ((uint32_t)1<<1); // TX enable
  to_mac.tx_configuration_vector |= ((uint32_t)1<<12); // 100Mb/s
  WIRE_WRITE(xil_tx_to_temac_t, xil_tx_to_temac, to_mac) // xil_tx_to_temac = to_mac
}

// Neural network specific code
#include "neural_network_eth_app.c"