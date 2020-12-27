#pragma once
#include "uintN_t.h"
#include "bit_manip.h"
#include "axis.h"

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
      
      // Only change state if was ready for frame data
      if(frame_ready)
      {
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
      }
      else
      {
        // Not ready for payload data output - overflow if data was incoming
        output.overflow = mac_axis.valid;
      }
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
  static axis16_t slice1_tx;
  static axis16_t slice2_tx;
  static axis16_t slice3_tx;
  static axis16_t slice4_tx;
  static axis16_t slice5_tx;
  static axis16_t slice6_tx;
  
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
    output.mac_axis.valid = eth.payload.valid;
    
    // Save payload for later
    output.frame_ready = mac_ready;
    axis32_t axis0;
    axis0 = eth.payload;
    uint1_t has_lsb_data;
    has_lsb_data = uint4_1_1(axis0.keep);
    
    // Next state if mac ready + wait for start valid
    if(mac_ready & eth.payload.valid)
    { 
      state = DST_MAC_LSB_SRC_MAC_MSB;
      slice0_tx.data = uint32_31_16(axis0.data);
      slice1_tx.data = uint32_15_0(axis0.data);
      slice0_tx.keep = uint4_3_2(axis0.keep);
      slice1_tx.keep = uint4_1_0(axis0.keep);
      slice0_tx.last = axis0.last & !has_lsb_data;
      slice1_tx.last = axis0.last;
      slice0_tx.valid = axis0.valid;
      slice1_tx.valid = axis0.valid & has_lsb_data;
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
    
    // Save payload for later
    output.frame_ready = mac_ready;
    axis32_t axis1;
    axis1 = eth.payload;
    uint1_t has_lsb_data;
    has_lsb_data = uint4_1_1(axis1.keep);
    
    // Next state if mac ready
    if(mac_ready)
    {
      state = SRC_MAC_LSB;
      slice2_tx.data = uint32_31_16(axis1.data);
      slice3_tx.data = uint32_15_0(axis1.data);
      slice2_tx.keep = uint4_3_2(axis1.keep);
      slice3_tx.keep = uint4_1_0(axis1.keep);
      slice2_tx.last = axis1.last & !has_lsb_data;
      slice3_tx.last = axis1.last;
      slice2_tx.valid = axis1.valid;
      slice3_tx.valid = axis1.valid & has_lsb_data;
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
    
    // Save payload for later
    output.frame_ready = mac_ready;
    axis32_t axis2;
    axis2 = eth.payload;    
    uint1_t has_lsb_data;
    has_lsb_data = uint4_1_1(axis2.keep);
    
    // Next state if mac ready
    if(mac_ready)
    {
      state = LEN_PAYLOAD_MSB_BUFF_INIT;
      slice4_tx.data = uint32_31_16(axis2.data);
      slice5_tx.data = uint32_15_0(axis2.data);
      slice4_tx.keep = uint4_3_2(axis2.keep);
      slice5_tx.keep = uint4_1_0(axis2.keep);
      slice4_tx.last = axis2.last & !has_lsb_data;
      slice5_tx.last = axis2.last;
      slice4_tx.valid = axis2.valid;
      slice5_tx.valid = axis2.valid & has_lsb_data;
    }
  }
  else if(state==LEN_PAYLOAD_MSB_BUFF_INIT)
  {
    // Output length and guarenteed valid slice0_tx data
    output.mac_axis.valid = 1;
    output.mac_axis.data = uint16_uint16(eth.header.ethertype, slice0_tx.data); // Uhh ethertype filled in by TEMAC?
    output.mac_axis.keep = 15;
    output.mac_axis.last = 0;
    
    // End slices 5 and 6 get payload from this time
    // Save payload for later
    output.frame_ready = mac_ready;
    axis32_t axis3;
    axis3 = eth.payload;    
    uint1_t has_lsb_data;
    has_lsb_data = uint4_1_1(axis3.keep);   
    
    // Next state if mac ready
    if(mac_ready)
    {
      // Since output slice0_tx just now shift everything forward by 1
      // Now slice0_tx is the end part of an full AXIS
      // So slice1_tx and slice2_tx might be in/valid
      slice0_tx = slice1_tx;
      slice1_tx = slice2_tx;
      slice2_tx = slice3_tx;
      slice3_tx = slice4_tx;
      slice4_tx = slice5_tx;
      
      slice5_tx.data = uint32_31_16(axis3.data);
      slice6_tx.data = uint32_15_0(axis3.data);
      slice5_tx.keep = uint4_3_2(axis3.keep);
      slice6_tx.keep = uint4_1_0(axis3.keep);
      slice5_tx.last = axis3.last & !has_lsb_data;
      slice6_tx.last = axis3.last;
      slice5_tx.valid = axis3.valid;
      slice6_tx.valid = axis3.valid & has_lsb_data;
      
      // Only change state if slice0_tx is valid, 
      // which it should be guarenteed to be
      state = PAYLOAD; 
    }
  }
  else if(state==PAYLOAD)
  {
    // Curse, not 32 aligned
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
    }
    
    // DO STATE CHANGES / accept input IF MAC READY
    if(mac_ready)
    {
      // Back to idle if this was last
      if(is_last)
      {
        state = DST_MAC_MSB;
      }
    
      // Uh..
      // uh weird shifting needed?
      // WEIRD LOGIC but ALWAYS NEED TO SHIFT BY 2 since incoming data
      // No slices guarenteed valid?      
      // CASES:
      //  (00) Neither valid, shift 2
      //  (11) Both valid, shift 2
      //  (10) Only 0 valid, 1+2 are invalid (1 known not valid, and since from 32b axis 2 must be invalid too) , shift by 2 differently
      //  (01) This should never happen ? would be like keep = 0b0011
      uint1_t slice0_invalid;
      slice0_invalid = !slice0_tx.valid;
      uint1_t slice1_invalid;
      slice1_invalid = !slice1_tx.valid;
      uint1_t neither_valid;
      neither_valid = slice0_invalid & slice1_invalid;
      uint1_t shift2;
      shift2 = has_32b | neither_valid;
      uint1_t shift2_diff;
      shift2_diff = slice0_tx.valid;
      if(shift2)
      {
        // Shift out from 0 by 2
        slice0_tx = slice2_tx;
        slice1_tx = slice3_tx;
        slice2_tx = slice4_tx;
        slice3_tx = slice5_tx;
        slice4_tx = slice6_tx;        
      }
      else if(shift2_diff)
      {
        // Shift out from 1 by 2
        // SAME slice0_tx
        slice1_tx = slice3_tx;
        slice2_tx = slice4_tx;
        slice3_tx = slice5_tx;
        slice4_tx = slice6_tx;
      }
      
      // New data in slice 5 and 6
      // Save payload for later
      output.frame_ready = 1;
      axis32_t axis4;
      axis4 = eth.payload;
      uint1_t has_lsb_data;
      has_lsb_data = uint4_1_1(axis4.keep);
      slice5_tx.data = uint32_31_16(axis4.data);
      slice6_tx.data = uint32_15_0(axis4.data);
      slice5_tx.keep = uint4_3_2(axis4.keep);
      slice6_tx.keep = uint4_1_0(axis4.keep);
      slice5_tx.last = axis4.last & !has_lsb_data;
      slice6_tx.last = axis4.last;
      slice5_tx.valid = axis4.valid;
      slice6_tx.valid = axis4.valid & has_lsb_data;
    }
  }
  
  // This was written for big endian (didnt know axis was little endian) so change endianess of data and keep
  output.mac_axis.data = bswap_32(output.mac_axis.data);
  output.mac_axis.keep = uint4_0_3(output.mac_axis.keep);
  
  return output;
}

