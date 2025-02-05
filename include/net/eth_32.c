// TODO rename to .h
#pragma once
#include "uintN_t.h"
#include "arrays.h"
#include "bit_manip.h"
#include "stream/stream.h"
#include "axi/axis.h"
#include "net/eth.h"

typedef struct eth32_frame_t
{
  eth_header_t header;
  stream(axis32_t) payload;
} eth32_frame_t;

// States
typedef enum eth32_rx_state_t {
  IDLE_DST_MAC_MSB,
  DST_MAC_LSB_SRC_MAC_MSB,
  SRC_MAC_LSB,
  LEN_BUFF_INIT,
  PAYLOAD
} eth32_rx_state_t;

typedef struct eth_32_rx_t
{
  eth32_frame_t frame;
  uint1_t overflow;
  uint1_t start_of_packet;
} eth_32_rx_t;
eth_32_rx_t eth_32_rx(stream(axis32_t) mac_axis, uint1_t frame_ready)
{
  // State regs
  static stream(axis16_t) slice0;
  static eth32_rx_state_t state; // Parser state
  static eth_32_rx_t output; // Data to output
  static uint1_t start_of_packet;
  
  // This was written for big endian (didnt know axis was little endian) so change endianess of data and keep
  ARRAY_REV(uint8_t, mac_axis.data.tdata, 4)
  ARRAY_REV(uint1_t, mac_axis.data.tkeep, 4)
  uint32_t mac_axis_data = uint8_array4_le(mac_axis.data.tdata);

  // Default no payload
  output.frame.payload.valid = 0; 
  output.overflow = 0;
  output.start_of_packet = 0;

  if(state==IDLE_DST_MAC_MSB)
  {
    // DST MAC MSB
    uint32_t dst_mac_msb;
    dst_mac_msb = uint32_31_0(mac_axis_data);
    output.frame.header.dst_mac = uint48_uint32_16(output.frame.header.dst_mac,dst_mac_msb);
    
    // Next state
    if(mac_axis.valid)
    {
      state = DST_MAC_LSB_SRC_MAC_MSB;
    }
  }
  else if(state==DST_MAC_LSB_SRC_MAC_MSB)
  {
    // DST MAC LSB
    uint16_t dst_mac_lsb;
    dst_mac_lsb = uint32_31_16(mac_axis_data);
    output.frame.header.dst_mac = uint48_uint16_0(output.frame.header.dst_mac,dst_mac_lsb);
    // SRC MAC MSB
    uint16_t src_mac_msb;
    src_mac_msb = uint32_15_0(mac_axis_data);
    output.frame.header.src_mac = uint48_uint16_32(output.frame.header.src_mac,src_mac_msb);
    
    // Next state
    if(mac_axis.valid)
    {
      state = SRC_MAC_LSB;
    }
  }
  else if(state==SRC_MAC_LSB)
  {
    // SRC MAC LSB
    uint32_t src_mac_lsb;
    src_mac_lsb = uint32_31_0(mac_axis_data);
    output.frame.header.src_mac = uint48_uint32_0(output.frame.header.src_mac,src_mac_lsb);
    
    // Next state
    if(mac_axis.valid)
    {
      state = LEN_BUFF_INIT;
    }
  } 
  else if(state==LEN_BUFF_INIT)
  {
    // LENGTH
    output.frame.header.ethertype = uint32_31_16(mac_axis_data);
    // First two bytes of payload into buff
    slice0.data.tdata[1] = mac_axis.data.tdata[1];
    slice0.data.tdata[0] = mac_axis.data.tdata[0];
    slice0.data.tkeep[0] = 1;
    slice0.data.tkeep[1] = 1; // These two bytes must be there
    slice0.data.tlast = 0; // And not last
    slice0.valid = 1; // Is valid 
    // Next state
    if(mac_axis.valid)
    {
      state = PAYLOAD;
      start_of_packet = 1;
    }
  }
  else if(state==PAYLOAD)
  {
    // Break into three 16b slices
    // Slice0 always valid
    stream(axis16_t) slice1; // MSB of data
    slice1.valid = mac_axis.valid;
    slice1.data.tdata[1] = mac_axis.data.tdata[3];
    slice1.data.tdata[0] = mac_axis.data.tdata[2];
    slice1.data.tkeep[1] = mac_axis.data.tkeep[3];
    slice1.data.tkeep[0] = mac_axis.data.tkeep[2];
    uint1_t slice2_has_keep;
    slice2_has_keep = mac_axis.data.tkeep[1];
    slice1.data.tlast = mac_axis.data.tlast & ~slice2_has_keep;
    stream(axis16_t) slice2; // LSB of data
    slice2.valid = mac_axis.valid & slice2_has_keep;
    slice2.data.tdata[1] = mac_axis.data.tdata[1];
    slice2.data.tdata[0] = mac_axis.data.tdata[0];
    slice2.data.tkeep[1] = mac_axis.data.tkeep[1];
    slice2.data.tkeep[0] = mac_axis.data.tkeep[0];
    slice2.data.tlast = mac_axis.data.tlast;
    
    // Only output payload
    // if we have 32b of data OR last bit to output in first two slices
    // This could def be reduced
    uint1_t has_32b;
    has_32b = slice0.valid & slice1.valid;
    uint1_t slice0_is_last;
    slice0_is_last = slice0.valid & slice0.data.tlast;
    uint1_t slice1_is_last;
    slice1_is_last = slice1.valid & slice1.data.tlast;
    uint1_t is_last;
    is_last = slice0_is_last | slice1_is_last;
    if(has_32b | is_last)
    {
      // Output is valid
      output.frame.payload.valid = 1;
      // Maybe last 
      output.frame.payload.data.tlast = is_last;
      // MSB data is slice0, lsb slice1
      output.frame.payload.data.tdata[3] = slice0.data.tdata[1];
      output.frame.payload.data.tdata[2] = slice0.data.tdata[0];
      output.frame.payload.data.tdata[1] = slice1.data.tdata[1];
      output.frame.payload.data.tdata[0] = slice1.data.tdata[0];

      // Only keep slice1 lsb data if slice1 valid      
      uint1_t slice1_keep0;
      slice1_keep0 = slice1.data.tkeep[0] & slice1.valid;
      uint1_t slice1_keep1;
      slice1_keep1 = slice1.data.tkeep[1] & slice1.valid;
      output.frame.payload.data.tkeep[3] = slice0.data.tkeep[1];
      output.frame.payload.data.tkeep[2] = slice0.data.tkeep[0];
      output.frame.payload.data.tkeep[1] = slice1_keep1;
      output.frame.payload.data.tkeep[0] = slice1_keep0;
      // SOP from reg
      output.start_of_packet = start_of_packet;

      // Shift slices by 2 for next time
      // (need variable shift for back to back packets)
      // slice0 <= slice2
      slice0 = slice2;
      // slice1 <= null
      // slice2 <= null
      // Slice1 and 2 are inputs next time so dont need to overwrite
      
      // Back to idle if this was last
      if(is_last)
      {
        state = IDLE_DST_MAC_MSB;
      }
      
      // Clear SOP always, set only for first word
      start_of_packet = 0;

      // Not ready for payload data output - overflow if data was incoming
      output.overflow = mac_axis.valid & ~frame_ready;
    }
  }
  
  // This was written for big endian (didnt know axis was little endian) so change endianess of data and keep
  ARRAY_REV(uint8_t, output.frame.payload.data.tdata, 4)
  ARRAY_REV(uint1_t, output.frame.payload.data.tkeep, 4)

  return output;
}


typedef enum eth32_tx_state_t {
  DST_MAC_MSB,
  DST_MAC_LSB_SRC_MAC_MSB,
  SRC_MAC_LSB,
  LEN_PAYLOAD_MSB_BUFF_INIT,
  PAYLOAD
} eth32_tx_state_t;

typedef struct eth_32_tx_t
{
  uint1_t frame_ready;
  stream(axis32_t) mac_axis;
} eth_32_tx_t;
eth_32_tx_t eth_32_tx(eth32_frame_t eth, uint1_t mac_ready)
{
  // State regs
  static eth32_tx_state_t state;
  static eth_32_tx_t output;
  static stream(axis16_t) slice0_tx;
  
  // This was written for big endian (didnt know axis was little endian) so change endianess of data and keep
  ARRAY_REV(uint8_t, eth.payload.data.tdata, 4)
  ARRAY_REV(uint1_t, eth.payload.data.tkeep, 4)
  
  // Default no payload, not ready
  output.mac_axis.valid = 0;
  output.frame_ready = 0;
  
  if(state==DST_MAC_MSB)
  {
    // Build fields
    // DST MAC MSB
    uint32_t dst_mac_msb;
    dst_mac_msb = uint48_47_16(eth.header.dst_mac);
    
    // Output data
    UINT_TO_BYTE_ARRAY(output.mac_axis.data.tdata, 4, dst_mac_msb)
    ARRAY_SET(output.mac_axis.data.tkeep, 1, 4)
    output.mac_axis.data.tlast = 0;
    
    // Wait for valid payload first word to trigger start
    // not ready for payload yet though
    if(eth.payload.valid)
    {
      // Try to send word
      output.mac_axis.valid = 1;
      // Next state if mac was ready
      if(mac_ready)
      {
        state = DST_MAC_LSB_SRC_MAC_MSB;
      } 
    }      
  }
  else if(state==DST_MAC_LSB_SRC_MAC_MSB)
  {
    // Build fields
    // DST MAC LSB
    uint16_t dst_mac_lsb;
    dst_mac_lsb = uint48_15_0(eth.header.dst_mac);

    // SRC MAC MSB
    uint16_t src_mac_msb;
    src_mac_msb = uint48_47_32(eth.header.src_mac);
    
    // Output
    output.mac_axis.valid = 1;
    output.mac_axis.data.tdata[3] = dst_mac_lsb(15, 8);
    output.mac_axis.data.tdata[2] = dst_mac_lsb(7, 0);
    output.mac_axis.data.tdata[1] = src_mac_msb(15, 8);
    output.mac_axis.data.tdata[0] = src_mac_msb(7, 0);
    ARRAY_SET(output.mac_axis.data.tkeep, 1, 4)
    output.mac_axis.data.tlast = 0;
    
    // Next state if mac ready, not ready for payload yet though
    if(mac_ready)
    {
      state = SRC_MAC_LSB;
    }
  }
  else if(state==SRC_MAC_LSB)
  {
    // Build fields
    uint32_t src_mac_lsb;
    src_mac_lsb = uint48_31_0(eth.header.src_mac);

    // Output
    output.mac_axis.valid = 1;
    UINT_TO_BYTE_ARRAY(output.mac_axis.data.tdata, 4, src_mac_lsb)
    ARRAY_SET(output.mac_axis.data.tkeep, 1, 4)
    output.mac_axis.data.tlast = 0;

    // Next state if mac ready,not ready for payload yet though
    if(mac_ready)
    {
      state = LEN_PAYLOAD_MSB_BUFF_INIT;
    }
  }
  else if(state==LEN_PAYLOAD_MSB_BUFF_INIT)
  {
    // Payload into slices
    stream(axis16_t) slice1_tx;
    uint1_t has_lsb_data = eth.payload.data.tkeep[1];
    slice0_tx.data.tdata[1] = eth.payload.data.tdata[3];
    slice0_tx.data.tdata[0] = eth.payload.data.tdata[2];
    slice1_tx.data.tdata[1] = eth.payload.data.tdata[1];
    slice1_tx.data.tdata[0] = eth.payload.data.tdata[0];
    slice0_tx.data.tkeep[1] = eth.payload.data.tkeep[3];
    slice0_tx.data.tkeep[0] = eth.payload.data.tkeep[2];
    slice1_tx.data.tkeep[1] = eth.payload.data.tkeep[1];
    slice1_tx.data.tkeep[0] = eth.payload.data.tkeep[0];
    slice0_tx.data.tlast = eth.payload.data.tlast & !has_lsb_data;
    slice1_tx.data.tlast = eth.payload.data.tlast;
    slice0_tx.valid = eth.payload.valid;
    slice1_tx.valid = eth.payload.valid & has_lsb_data;
    
    // Output length and first two bytes of payload
    output.frame_ready = mac_ready;
    output.mac_axis.valid = slice0_tx.valid;
    output.mac_axis.data.tdata[3] = uint16_15_8(eth.header.ethertype);
    output.mac_axis.data.tdata[2] = uint16_7_0(eth.header.ethertype);
    output.mac_axis.data.tdata[1] = slice0_tx.data.tdata[1];
    output.mac_axis.data.tdata[0] = slice0_tx.data.tdata[0];
    output.mac_axis.data.tkeep[1] = slice0_tx.data.tkeep[1]; // Needed?
    output.mac_axis.data.tkeep[0] = slice0_tx.data.tkeep[0]; // Needed?
    output.mac_axis.data.tlast = slice0_tx.data.tlast;
    
    // Next state if mac ready for payload
    if(mac_ready & output.mac_axis.valid)
    {
      // Since output slice0_tx just now shift everything forward by 1
      slice0_tx = slice1_tx;
      state = PAYLOAD; 
    }
  }
  else if(state==PAYLOAD)
  {
    // Incoming payload into two slices (already have one from before, slice0_tx)
    stream(axis16_t) slice1_tx;
    stream(axis16_t) slice2_tx;
    uint1_t has_lsb_data = eth.payload.data.tkeep[1];
    slice1_tx.data.tdata[1] = eth.payload.data.tdata[3];
    slice1_tx.data.tdata[0] = eth.payload.data.tdata[2];
    slice2_tx.data.tdata[1] = eth.payload.data.tdata[1];
    slice2_tx.data.tdata[0] = eth.payload.data.tdata[0];
    slice1_tx.data.tkeep[1] = eth.payload.data.tkeep[3];
    slice1_tx.data.tkeep[0] = eth.payload.data.tkeep[2];
    slice2_tx.data.tkeep[1] = eth.payload.data.tkeep[1];
    slice2_tx.data.tkeep[0] = eth.payload.data.tkeep[0];
    slice1_tx.data.tlast = eth.payload.data.tlast & !has_lsb_data;
    slice2_tx.data.tlast = eth.payload.data.tlast;
    slice1_tx.valid = eth.payload.valid;
    slice2_tx.valid = eth.payload.valid & has_lsb_data;
    
    // Only change state / output payload
    // if we have 32b of data OR last bit to output in first two slices
    // AND MAC IS READY
    // This could def be reduced
    uint1_t has_32b;
    has_32b = slice0_tx.valid & slice1_tx.valid;
    uint1_t slice0_is_last;
    slice0_is_last = slice0_tx.valid & slice0_tx.data.tlast;
    uint1_t slice1_is_last;
    slice1_is_last = slice1_tx.valid & slice1_tx.data.tlast;
    uint1_t is_last;
    is_last = slice0_is_last | slice1_is_last;
    uint1_t has_32b_or_is_last;
    has_32b_or_is_last = has_32b | is_last;
    
    // Set output values
    if(has_32b_or_is_last)
    {
      output.frame_ready = mac_ready;
      // Output is valid
      output.mac_axis.valid = 1;
      // Maybe last 
      output.mac_axis.data.tlast = is_last;
      // MSB data is slice0_tx, lsb slice1_tx
      output.mac_axis.data.tdata[3] = slice0_tx.data.tdata[1];
      output.mac_axis.data.tdata[2] = slice0_tx.data.tdata[0];
      output.mac_axis.data.tdata[1] = slice1_tx.data.tdata[1];
      output.mac_axis.data.tdata[0] = slice1_tx.data.tdata[0];
      
      // Only keep slice1_tx lsb data if slice1_tx valid          
      uint1_t slice1_keep0;
      slice1_keep0 = slice1_tx.data.tkeep[0] & slice1_tx.valid;
      uint1_t slice1_keep1;
      slice1_keep1 = slice1_tx.data.tkeep[1] & slice1_tx.valid;
      output.mac_axis.data.tkeep[3] = slice0_tx.data.tkeep[1];
      output.mac_axis.data.tkeep[2] = slice0_tx.data.tkeep[0];
      output.mac_axis.data.tkeep[1] = slice1_keep1;
      output.mac_axis.data.tkeep[0] = slice1_keep0;      
      
      // DO STATE CHANGES / accept input IF MAC READY
      if(mac_ready)
      {
        // Shift by 2 for the two words just sent
        slice0_tx = slice2_tx;
        
        // Back to idle if this was last
        if(is_last)
        {
          state = DST_MAC_MSB;
        }
      }
    }
    // Nothing else needed? Dont get weird shifting cases since using flow control right?
  }
  
  // This was written for big endian (didnt know axis was little endian) so change endianess of data and keep
  ARRAY_REV(uint8_t, output.mac_axis.data.tdata, 4)
  ARRAY_REV(uint1_t, output.mac_axis.data.tkeep, 4)
  
  return output;
}

