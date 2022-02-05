#pragma once
#include "uintN_t.h"
#include "bit_manip.h"
#include "axi/axis.h"

typedef struct eth_header_t
{
  uint48_t src_mac;
  uint48_t dst_mac;
  uint16_t ethertype;
} eth_header_t;

typedef struct eth32_frame_t
{
  eth_header_t header;
  axis32_t payload;
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
eth_32_rx_t eth_32_rx(axis32_t mac_axis, uint1_t frame_ready)
{
  // State regs
  static axis16_t slice0;
  static eth32_rx_state_t state; // Parser state
  static eth_32_rx_t output; // Data to output
  static uint1_t start_of_packet;
  
  // This was written for big endian (didnt know axis was little endian) so change endianess of data and keep
  mac_axis.data = bswap_32(mac_axis.data);
  mac_axis.keep = uint4_0_3(mac_axis.keep);
  
  // Default no payload
  output.frame.payload.valid = 0; 
  output.overflow = 0;
  output.start_of_packet = 0;

  if(state==IDLE_DST_MAC_MSB)
  {
    // DST MAC MSB
    uint32_t dst_mac_msb;
    dst_mac_msb = uint32_31_0(mac_axis.data);
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
    dst_mac_lsb = uint32_31_16(mac_axis.data);
    output.frame.header.dst_mac = uint48_uint16_0(output.frame.header.dst_mac,dst_mac_lsb);
    // SRC MAC MSB
    uint16_t src_mac_msb;
    src_mac_msb = uint32_15_0(mac_axis.data);
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
    src_mac_lsb = uint32_31_0(mac_axis.data);
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
    output.frame.header.ethertype = uint32_31_16(mac_axis.data);
    // First two bytes of payload into buff
    slice0.data = uint32_15_0(mac_axis.data);
    slice0.keep = 3; // These two bytes must be there
    slice0.last = 0; // And not last
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
    axis16_t slice1; // MSB of data
    slice1.valid = mac_axis.valid;
    slice1.data = uint32_31_16(mac_axis.data);
    slice1.keep = uint4_3_2(mac_axis.keep);
    uint1_t slice2_has_keep;
    slice2_has_keep = uint4_1_1(mac_axis.keep);
    slice1.last = mac_axis.last & !slice2_has_keep;
    axis16_t slice2; // LSB of data
    slice2.valid = mac_axis.valid & slice2_has_keep;
    slice2.data = uint32_15_0(mac_axis.data);
    slice2.keep = uint4_1_0(mac_axis.keep);
    slice2.last = mac_axis.last;
    
    // Only output payload
    // if we have 32b of data OR last bit to output in first two slices
    // This could def be reduced
    uint1_t has_32b;
    has_32b = slice0.valid & slice1.valid;
    uint1_t slice0_is_last;
    slice0_is_last = slice0.valid & slice0.last;
    uint1_t slice1_is_last;
    slice1_is_last = slice1.valid & slice1.last;
    uint1_t is_last;
    is_last = slice0_is_last | slice1_is_last;
    if(has_32b | is_last)
    {
      // Output is valid
      output.frame.payload.valid = 1;
      // Maybe last 
      output.frame.payload.last = is_last;
      // MSB data is slice0, lsb slice1
      output.frame.payload.data = uint16_uint16(slice0.data,slice1.data);
      // Only keep slice1 lsb data if slice1 valid      
      uint1_t slice1_keep0;
      slice1_keep0 = uint2_0_0(slice1.keep) & slice1.valid;
      uint1_t slice1_keep1;
      slice1_keep1 = uint2_1_1(slice1.keep) & slice1.valid;
      uint2_t slice1_keep;
      slice1_keep = uint1_uint1(slice1_keep1,slice1_keep0);
      output.frame.payload.keep = uint2_uint2(slice0.keep,slice1_keep);
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
      output.overflow = mac_axis.valid & !frame_ready;
    }
  }
  
  // This was written for big endian (didnt know axis was little endian) so change endianess of data and keep
  output.frame.payload.data = bswap_32(output.frame.payload.data);
  output.frame.payload.keep = uint4_0_3(output.frame.payload.keep);
  
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
  axis32_t mac_axis;
} eth_32_tx_t;
eth_32_tx_t eth_32_tx(eth32_frame_t eth, uint1_t mac_ready)
{
  // State regs
  static eth32_tx_state_t state;
  static eth_32_tx_t output;
  static axis16_t slice0_tx;
  
  // This was written for big endian (didnt know axis was little endian) so change endianess of data and keep
  eth.payload.data = bswap_32(eth.payload.data);
  eth.payload.keep = uint4_0_3(eth.payload.keep);
  
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
    output.mac_axis.data = dst_mac_msb;
    output.mac_axis.keep = 15;
    output.mac_axis.last = 0;
    
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
    output.mac_axis.data = uint16_uint16(dst_mac_lsb, src_mac_msb);
    output.mac_axis.keep = 15;
    output.mac_axis.last = 0;
    
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
    output.mac_axis.data = src_mac_lsb;
    output.mac_axis.keep = 15;
    output.mac_axis.last = 0;

    // Next state if mac ready,not ready for payload yet though
    if(mac_ready)
    {
      state = LEN_PAYLOAD_MSB_BUFF_INIT;
    }
  }
  else if(state==LEN_PAYLOAD_MSB_BUFF_INIT)
  {
    // Payload into slices
    axis16_t slice1_tx;
    uint1_t has_lsb_data = uint4_1_1(eth.payload.keep);
    slice0_tx.data = uint32_31_16(eth.payload.data);
    slice1_tx.data = uint32_15_0(eth.payload.data);
    slice0_tx.keep = uint4_3_2(eth.payload.keep);
    slice1_tx.keep = uint4_1_0(eth.payload.keep);
    slice0_tx.last = eth.payload.last & !has_lsb_data;
    slice1_tx.last = eth.payload.last;
    slice0_tx.valid = eth.payload.valid;
    slice1_tx.valid = eth.payload.valid & has_lsb_data;
    
    // Output length and first two bytes of payload
    output.frame_ready = mac_ready;
    output.mac_axis.valid = slice0_tx.valid;
    output.mac_axis.data = uint16_uint16(eth.header.ethertype, slice0_tx.data);
    output.mac_axis.keep = slice0_tx.keep;
    output.mac_axis.last = slice0_tx.last;
    
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
    axis16_t slice1_tx;
    axis16_t slice2_tx;
    uint1_t has_lsb_data = uint4_1_1(eth.payload.keep);
    slice1_tx.data = uint32_31_16(eth.payload.data);
    slice2_tx.data = uint32_15_0(eth.payload.data);
    slice1_tx.keep = uint4_3_2(eth.payload.keep);
    slice2_tx.keep = uint4_1_0(eth.payload.keep);
    slice1_tx.last = eth.payload.last & !has_lsb_data;
    slice2_tx.last = eth.payload.last;
    slice1_tx.valid = eth.payload.valid;
    slice2_tx.valid = eth.payload.valid & has_lsb_data;
    
    // Only change state / output payload
    // if we have 32b of data OR last bit to output in first two slices
    // AND MAC IS READY
    // This could def be reduced
    uint1_t has_32b;
    has_32b = slice0_tx.valid & slice1_tx.valid;
    uint1_t slice0_is_last;
    slice0_is_last = slice0_tx.valid & slice0_tx.last;
    uint1_t slice1_is_last;
    slice1_is_last = slice1_tx.valid & slice1_tx.last;
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
      output.mac_axis.last = is_last;
      // MSB data is slice0_tx, lsb slice1_tx
      output.mac_axis.data = uint16_uint16(slice0_tx.data,slice1_tx.data);
      
      // Only keep slice1_tx lsb data if slice1_tx valid          
      uint1_t slice1_keep0;
      slice1_keep0 = uint2_0_0(slice1_tx.keep) & slice1_tx.valid;
      uint1_t slice1_keep1;
      slice1_keep1 = uint2_1_1(slice1_tx.keep) & slice1_tx.valid;
      uint2_t slice1_keep;
      slice1_keep = uint1_uint1(slice1_keep1,slice1_keep0);
      output.mac_axis.keep = uint2_uint2(slice0_tx.keep,slice1_keep);
      
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
  output.mac_axis.data = bswap_32(output.mac_axis.data);
  output.mac_axis.keep = uint4_0_3(output.mac_axis.keep);
  
  return output;
}

