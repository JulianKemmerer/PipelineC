// CPU 1 host -> N devices addr decoder
// device is at end of decoder

#include "axi/axi_shared_bus.h" // s 'axi_shared_bus_t' type things
// axi_shared_bus_t_dev_to_host_t // For wires from device (S) to host (M)
// axi_shared_bus_t_host_to_dev_t // For wires from host (M) to device)
//  ex.
//  from_host.read.req.data.user.araddr // AR channel address
//  from_host.read.req.valid // AR channel valid
//  o.to_host.read.req_ready // AR channel ready


typedef struct addr_range_t{
  uint32_t start;
  uint32_t end;
}addr_range_t;
#define NDECODE 2 // TODO use macros for name too
typedef struct axi_shared_bus_addr_decode_2_t{
  axi_shared_bus_t_host_to_dev_t to_devs[NDECODE];
  axi_shared_bus_t_dev_to_host_t to_host;
}axi_shared_bus_addr_decode_2_t;
axi_shared_bus_addr_decode_2_t axi_shared_bus_addr_decode_2(
  axi_shared_bus_t_host_to_dev_t from_host,
  axi_shared_bus_t_dev_to_host_t from_devs[NDECODE],
  addr_range_t addr_map[NDECODE]
){
  axi_shared_bus_addr_decode_2_t o;

  // Independent read and write sides

  // Which device is connected through muxing?
  static uint1_t rd_is_connected;
  static uint8_t rd_selected_dev_index; // TODO do one-hot instead?
  if(rd_is_connected){
    // Connect input from host to selected device
    o.to_devs[rd_selected_dev_index].read = from_host.read;
    // Connect input from selected device to host
    o.to_host.read = from_devs[rd_selected_dev_index].read;
    // Until read response goes through
    // Assuming only one xfer in flight...
    if(o.to_host.read.data.valid & from_host.read.data_ready){
      rd_is_connected = 0;
    }
  }else{
    // Decode read address to selected device to connect
    // cheating a little on axi spec, waiting for valid before signaling ready
    if(from_host.read.req.valid){ 
      for(uint32_t i = 0; i < NDECODE; i+=1)
      {
        if( (from_host.read.req.data.user.araddr >= addr_map[i].start) &
            (from_host.read.req.data.user.araddr <= addr_map[i].end)
        ){
          rd_selected_dev_index = i;
          rd_is_connected = 1;
        }
      }
    }
  }
  
  // Which device is connected through muxing?
  static uint1_t wr_is_connected;
  static uint8_t wr_selected_dev_index; // TODO do one-hot instead?
  if(wr_is_connected){
    // Connect input from host to selected device
    o.to_devs[wr_selected_dev_index].write = from_host.write;
    // Connect input from selected device to host
    o.to_host.write = from_devs[wr_selected_dev_index].write;
    // Until write response goes through
    // Assuming only one xfer in flight...
    if(o.to_host.write.resp.valid & from_host.write.resp_ready){
      wr_is_connected = 0;
    }
  }else{
    // Decode write address to selected device to connect
    // cheating a little on axi spec, waiting for valid before signaling ready
    if(from_host.write.req.valid){ 
      for(uint32_t i = 0; i < NDECODE; i+=1)
      {
        if( (from_host.write.req.data.user.awaddr >= addr_map[i].start) &
            (from_host.write.req.data.user.awaddr <= addr_map[i].end)
        ){
          wr_selected_dev_index = i;
          wr_is_connected = 1;
        }
      }
    }
  }

  return o;
}


typedef struct my_axil_dev_outputs_t{
  axi_shared_bus_t_dev_to_host_t to_host;
}my_axil_dev_outputs_t;
my_axil_dev_outputs_t my_axil_dev(
  axi_shared_bus_t_host_to_dev_t from_host
){
  my_axil_dev_outputs_t o;

  // AR channel buffer regs
  static axi_shared_bus_t_read_req_data_t rd_req;
  static uint1_t rd_req_valid;

  // AW channel buffer regs
  static axi_shared_bus_t_write_req_data_t wr_req;
  static uint1_t wr_req_valid;

  // W channel buffer regs
  static axi_shared_bus_t_write_data_word_t wr_data;
  static uint1_t wr_data_valid;

  // R channel buffer regs
  static axi_shared_bus_t_read_data_resp_word_t rd_data;
  static uint1_t rd_data_valid;

  // B channel buffer regs
  static axi_shared_bus_t_write_resp_data_t wr_resp;
  static uint1_t wr_resp_valid;

  // R channel buffer output handshake
  o.to_host.read.data.burst.data_resp = rd_data;
  o.to_host.read.data.valid = rd_data_valid;
  if(o.to_host.read.data.valid & from_host.read.data_ready){
    rd_data_valid = 0;
    // Also clears input side handshake
    // TODO get rid of comb logic between resp and req
    rd_req_valid = 0;
  }

  // B channel buffer output handshake
  o.to_host.write.resp.data = wr_resp;
  o.to_host.write.resp.valid = wr_resp_valid;
  if(o.to_host.write.resp.valid & from_host.write.resp_ready){
    wr_resp_valid = 0;
    // Also clears input side handshake
    // TODO get rid of comb logic between resp and req
    wr_req_valid = 0;
    wr_data_valid = 0;
  }

  // Some 32b words test...
  #define NWORDS 8
  static uint8_t word_bytes_reg[NWORDS][4];

  // Handle read request and response
  uint30_t rd_req_word_addr = rd_req.user.araddr >> 2;
  // Only LSBs of addr used
  rd_data.user.rdata = word_bytes_reg[rd_req_word_addr];
  rd_data_valid = rd_req_valid;

  // Handle write request and response
  uint30_t wr_req_word_addr = wr_req.user.awaddr >> 2;
  if(wr_req_valid & wr_data_valid){
    for (uint32_t i = 0; i < 4; i+=1)
    {
      if(wr_data.user.wstrb[i]){
        // Only LSBs of addr used
        word_bytes_reg[wr_req_word_addr][i] = wr_data.user.wdata[i];
      }
    }
    wr_resp.user.bresp = 0; // No error
    wr_resp_valid = 1;
  }

  // AR channel buffer input handshake
  o.to_host.read.req_ready = ~rd_req_valid;
  if(from_host.read.req.valid & o.to_host.read.req_ready){
    rd_req = from_host.read.req.data;
    rd_req_valid = 1;
  }

  // AW channel buffer input handshake
  o.to_host.write.req_ready = ~wr_req_valid;
  if(from_host.write.req.valid & o.to_host.write.req_ready){
    wr_req = from_host.write.req.data;
    wr_req_valid = 1;
  }
  
  // W channel buffer input handshake
  o.to_host.write.data_ready = ~wr_data_valid;
  if(from_host.write.data.valid & o.to_host.write.data_ready){
    wr_data = from_host.write.data.burst.data_word;
    wr_data_valid = 1;
  }

  return o;
}


// Globally visible wires for SoC to connect to
axi_shared_bus_t_dev_to_host_t axi_lite_demo_to_host;
axi_shared_bus_t_host_to_dev_t axi_lite_demo_from_host;

#pragma MAIN axi_lite_demo_main
void axi_lite_demo_main()
{
  // Instance of the 1 CPU host -> N devices addr decoder
  // Test addr map with two devices both given bottom 16b of addr range
  addr_range_t addr_map[NDECODE] = {
    {.start = 0x00000, .end = 0x0FFFF},
    {.start = 0x10000, .end = 0x1FFFF}
  };
  axi_shared_bus_t_dev_to_host_t from_devs[NDECODE];
  #pragma FEEDBACK from_devs // Not driven until later below
  axi_shared_bus_addr_decode_2_t decode = axi_shared_bus_addr_decode_2(
    axi_lite_demo_from_host,
    from_devs,
    addr_map
  );
  axi_lite_demo_to_host = decode.to_host;

  // N instances of the device
  for(uint32_t i = 0; i < NDECODE; i+=1)
  {
    my_axil_dev_outputs_t dev = my_axil_dev(decode.to_devs[i]);
    from_devs[i] = dev.to_host;
  }
}
