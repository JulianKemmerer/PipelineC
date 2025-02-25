#pragma once
#include "uintN_t.h"
#include "arrays.h"
#include "bit_manip.h"
#include "stream/stream.h"
#include "axi/axis.h"
#include "net/eth.h"

typedef struct eth8_frame_t
{
  eth_header_t header;
  axis8_t payload;
  uint1_t start_of_payload;
} eth8_frame_t;
DECL_STREAM_TYPE(eth8_frame_t)

// FSM states for 8b wide ethernet
typedef enum eth8_state_t {
  IDLE_DST_MAC,
  SRC_MAC,
  LEN_TYPE,
  PAYLOAD,
  PADDING
} eth8_state_t;

// 8b RX FSM
typedef struct eth_8_rx_t
{
  stream(eth8_frame_t) frame;
  uint1_t overflow;
} eth_8_rx_t;
eth_8_rx_t eth_8_rx(
  stream(axis8_t) mac_axis,
  uint1_t frame_ready
){
  // State regs
  static eth8_state_t state;
  static eth_header_t header;
  static uint3_t counter;

  // Default no output
  eth_8_rx_t o;
  o.frame.data.header = header;
  o.frame.data.start_of_payload = 0;
  o.frame.valid = 0; 
  o.overflow = 0;

  // FSM using counter to parse bytes of each ethernet field
  // MAC+LEN/TYPE MSBs are first
  // shift into bottom so at end of data MSBs are in right positon
  if(state == IDLE_DST_MAC){
    if(mac_axis.valid){
      header.dst_mac = uint40_uint8(header.dst_mac, mac_axis.data.tdata[0]);
      if(counter==(MAC_LEN-1)){
        state = SRC_MAC;
        counter = 0;
      }else{
        counter += 1;
      }
    }
  }else if(state == SRC_MAC){
    if(mac_axis.valid){
      header.src_mac = uint40_uint8(header.src_mac, mac_axis.data.tdata[0]);
      if(counter==(MAC_LEN-1)){
        state = LEN_TYPE;
        counter = 0;
      }else{
        counter += 1;
      }
    }
  }else if(state == LEN_TYPE){
    if(mac_axis.valid){
      header.ethertype = uint8_uint8(header.ethertype, mac_axis.data.tdata[0]);
      if(counter==(ETHERTYPE_LEN-1)){
        state = PAYLOAD;
        counter = 0;
      }else{
        counter += 1;
      }
    }
  }
  // Pass through payload bytes
  else if(state == PAYLOAD){
    // Output
    o.frame.data.payload = mac_axis.data;
    o.frame.data.start_of_payload = counter==0;
    o.frame.valid = mac_axis.valid;
    // No ready used, overflow if have data and not ready
    o.overflow = o.frame.valid & ~frame_ready;
    if(o.frame.valid){
      if(o.frame.data.start_of_payload){
        counter += 1;
      }
      if(o.frame.data.payload.tlast){
        state = IDLE_DST_MAC;
        counter = 0;
      }
    }
  }
  return o;
}

// 8b TX FSM
typedef struct eth_8_tx_t
{
  stream(axis8_t) mac_axis;
  uint1_t frame_ready;
} eth_8_tx_t;
eth_8_tx_t eth_8_tx(
  stream(eth8_frame_t) frame,
  uint1_t mac_axis_ready
){
  // State regs
  static eth8_state_t state;
  static eth_header_t header;
  static uint6_t counter;
  
  // Default no payload, not ready
  eth_8_tx_t o;
  o.mac_axis.data.tkeep[0] = 1;
  o.mac_axis.valid = 0;
  o.frame_ready = 0;
  // Count payload bytes for min size
  uint1_t undersized_payload = counter < ((64-(14+4))-1);

  // FSM using counter to build bytes of each ethernet field
  // MAC+LEN/TYPE MSBs are first, shift from top
  if(state == IDLE_DST_MAC){
    // Wait for frame to TX
    if(frame.valid){
      if(counter==0){
        header = frame.data.header;
      }
      o.mac_axis.valid = 1;
      o.mac_axis.data.tdata[0] = uint48_47_40(header.dst_mac);
      if(mac_axis_ready){
        header.dst_mac = header.dst_mac << 8;
        if(counter == (MAC_LEN-1)){
          state = SRC_MAC;
          counter = 0;
        }else{
          counter += 1;
        }
      }
    }
  }else if(state == SRC_MAC){
    o.mac_axis.valid = 1;
    o.mac_axis.data.tdata[0] = uint48_47_40(header.src_mac);
    if(mac_axis_ready){
      header.src_mac = header.src_mac << 8;
      if(counter == (MAC_LEN-1)){
        state = LEN_TYPE;
        counter = 0;
      }else{
        counter += 1;
      }
    }
  }else if(state == LEN_TYPE){
    o.mac_axis.valid = 1;
    o.mac_axis.data.tdata[0] = uint16_15_8(header.ethertype);
    if(mac_axis_ready){
      header.ethertype = header.ethertype << 8;
      if(counter == (ETHERTYPE_LEN-1)){
        state = PAYLOAD;
        counter = 0;
      }else{
        counter += 1;
      }
    }
  }
  // Pass through payload bytes
  else if(state == PAYLOAD){
    // Output
    o.mac_axis.data = frame.data.payload;
    // tlast let through if not undersized
    o.mac_axis.data.tlast = undersized_payload ? 0 : frame.data.payload.tlast;
    o.mac_axis.valid = frame.valid; 
    o.frame_ready = mac_axis_ready;
    if(o.mac_axis.valid & mac_axis_ready){
      if(frame.data.payload.tlast){
        // Add padding after user frame payload?
        if(undersized_payload){
          state = PADDING;
        }else{
          state = IDLE_DST_MAC;
          counter = 0;
        }
      }
      if(undersized_payload){
        counter += 1;
      }
    }
  }
  // Zeros for extra padding as needed
  else if(state == PADDING){
    o.mac_axis.data.tdata[0] = 0;
    o.mac_axis.data.tlast = ~undersized_payload;
    o.mac_axis.valid = 1;
    if(o.mac_axis.valid & mac_axis_ready){
      counter += 1;
      if(o.mac_axis.data.tlast){
        state = IDLE_DST_MAC;
        counter = 0;
      }
    }
  }
  return o;
}