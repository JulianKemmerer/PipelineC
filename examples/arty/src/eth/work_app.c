// Include board media access controller (8b AXIS)
#include "xil_temac.c"

// Include logic for parsing ethernet frames from 32b AXIS
#include "eth_32.c"

// Include the mac address info we want the fpga to have
#include "fpga_mac.h"

// Definition of work to do
#include "../work/work.h"

// Helper functions to convert uart bytes to/from 'work' inputs/outputs
// TODO gen includes all inside work_in|output_t_bytes_t.h
#include "uint8_t_array_N_t.h" 
#include "uint8_t_bytes_t.h"
#include "int16_t_bytes_t.h"
#include "work_inputs_t_bytes_t.h"
#include "work_outputs_t_bytes_t.h"

eth_header_t headers_fifo[2];
#include "headers_fifo_clock_crossing.h"

#include "deserializer.h"
#define DESER_IN_SIZE 4
deserializer_in_to_out(deserializer_to_type_deserializer, uint8_t, DESER_IN_SIZE, sizeof(work_inputs_t))

// MACRO FI THIS in deser.h
typedef struct type_deserializer_t
{
  work_inputs_t data;
  uint1_t valid;
  uint1_t in_data_ready;
}type_deserializer_t;
type_deserializer_t deserializer_to_type(uint8_t in_data[DESER_IN_SIZE], uint1_t in_data_valid, uint1_t out_data_ready)
{
  // Deserialize to byte array
  type_deserializer_t o;
  deserializer_to_type_deserializer_t to_type_bytes = deserializer_to_type_deserializer(in_data, in_data_valid, out_data_ready);
  // Byte array to type
  work_inputs_t_bytes_t output_bytes;
  output_bytes.data = to_type_bytes.out_data;
  o.data = bytes_to_work_inputs_t(output_bytes);
  o.valid = to_type_bytes.out_data_valid;
  o.in_data_ready = to_type_bytes.in_data_ready;
  return o;
}

// MACRO FI in axis.h
typedef struct axis_to_input_t
{
  work_inputs_t data;
  uint1_t valid;
  uint1_t payload_ready;
}axis_to_input_t;
axis_to_input_t axis_to_input(axis32_t payload, uint1_t output_ready)
{
  // AXIS to byte stream
  axis_to_input_t o;
  uint8_t input_data[DESER_IN_SIZE];
  uint32_t i;
  for(i=0;i<DESER_IN_SIZE;i+=1)
  {
    input_data[i] = payload.data >> (i*8);
  }
  // Deserialize byte stream to type
  type_deserializer_t to_type = deserializer_to_type(input_data, payload.valid, output_ready);
  o.data = to_type.data;
  o.valid = to_type.valid;
  o.payload_ready = to_type.in_data_ready;
  return o;
}


work_inputs_t inputs_fifo[16];
#include "inputs_fifo_clock_crossing.h"

#pragma MAIN_GROUP rx_main xil_temac_rx // Same clock group as Xilinx TEMAC, infers clock from group + clock crossings
void rx_main()
{
  // Read wire from RX MAC
  xil_temac_to_rx_t from_mac;
  WIRE_READ(xil_temac_to_rx_t, from_mac, xil_temac_to_rx) // from_mac = xil_temac_to_rx
  // The stream of data from the RX MAC
  axis8_t mac_axis_rx = from_mac.rx_axis_mac;
  
  // TODO stats+reset+enable

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
  
  // Data deserializer payload into messages which writes into fifo
  uint1_t deserializer_output_ready;
  #pragma FEEDBACK deserializer_output_ready
  axis_to_input_t to_input = axis_to_input(frame.payload,deserializer_output_ready);

  // Frame was ready if axis32_to_inputs+header fifo was ready
  eth_rx_out_ready = to_input.payload_ready & header_write.ready; // FEEDBACK

  // Write inputs into fifo
  work_inputs_t input_wr_data[1];
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
  to_mac.rx_configuration_vector |= (1<<1); // RX enable
  to_mac.rx_configuration_vector |= (1<<12); // 100Mb/s 
  WIRE_WRITE(xil_rx_to_temac_t, xil_rx_to_temac, to_mac) // xil_rx_to_temac = to_mac
}

#include "serializer.h"
#define SER_OUT_SIZE 4
serializer_in_to_out(serialize_from_type_serializer, uint8_t, sizeof(work_outputs_t), SER_OUT_SIZE)

// MACRO FI THIS in ser.h
typedef struct type_serializer_t
{
  uint8_t out_data[SER_OUT_SIZE];
  uint1_t valid;
  uint1_t in_data_ready;
}type_serializer_t;
type_serializer_t serialize_from_type(work_outputs_t in_data, uint1_t in_data_valid, uint1_t out_data_ready)
{
  // Convert type to byte array
  work_outputs_t_bytes_t input_bytes = work_outputs_t_to_bytes(in_data);
  // Serialize byte array
  type_serializer_t o;
  serialize_from_type_serializer_t to_bytes = serialize_from_type_serializer(input_bytes.data, in_data_valid, out_data_ready);
  o.out_data = to_bytes.out_data;
  o.valid = to_bytes.out_data_valid;
  o.in_data_ready = to_bytes.in_data_ready;
  return o;
}

// MACRO FI in axis.h
typedef struct output_to_axis_t
{
  axis32_t payload;
  uint1_t input_data_ready;
}output_to_axis_t;
output_to_axis_t output_to_axis(work_outputs_t data, uint1_t valid, uint1_t output_ready)
{
  output_to_axis_t o;
  
  // Serialize type to byte stream
  type_serializer_t from_type = serialize_from_type(data, valid, output_ready);
  o.input_data_ready = from_type.in_data_ready;
  
  // Byte stream to axis
  o.payload.data = 0;
  uint32_t i;
  for(i=0;i<SER_OUT_SIZE;i+=1)
  {
    uint32_t out_data_32b = from_type.out_data[i]; // Temp avoid not implemented cast
    o.payload.data |= (out_data_32b<<(i*8));
  }
  o.payload.keep = 0xF;
  o.payload.valid = from_type.valid;
  o.payload.last = 0;
  // Counter for last assertion
  static uint32_t last_counter; // TODO smaller counter?
  if(o.payload.valid & output_ready)
  {
    if(last_counter >= (sizeof(work_outputs_t)-SER_OUT_SIZE))
    {
      o.payload.last = 1;
      last_counter = 0;
    }
    else
    {
      last_counter = last_counter+SER_OUT_SIZE;
    }
  }
  return o;  
}


work_outputs_t outputs_fifo[16];
#include "outputs_fifo_clock_crossing.h"

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
  
  // Read header out of fifo
  uint1_t header_read_en;
  #pragma FEEDBACK header_read_en
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
  header_read_en = eth_tx.frame_ready & frame.payload.last & frame.payload.valid; // FEEDBACK
    
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
  to_mac.tx_configuration_vector |= (1<<1); // TX enable
  to_mac.tx_configuration_vector |= (1<<12); // 100Mb/s
  WIRE_WRITE(xil_tx_to_temac_t, xil_tx_to_temac, to_mac) // xil_tx_to_temac = to_mac
}



// This pipeline does the following:
//    Reads work inputs from rx fifo
//    Does work on the work inputs to form the work outputs
//    Writes outputs into tx fifo
#pragma MAIN_MHZ work_pipeline 150.0   // Actually running at 100MHz but need margin since near max utilization
void work_pipeline()
{
  // Read incoming work inputs from rx_main
  inputs_fifo_read_t input_read = inputs_fifo_READ_1(1); 
  work_inputs_t inputs = input_read.data[0]; 
  
  // Do work on inputs, get outputs
  work_outputs_t outputs = work(inputs);

  // Write outgoing work outputs into tx_main
  work_outputs_t output_wr_data[1];
  output_wr_data[0] = outputs;
  outputs_fifo_write_t output_write = outputs_fifo_WRITE_1(output_wr_data, input_read.valid);
  // TODO overflow wire+separate state
}






























































