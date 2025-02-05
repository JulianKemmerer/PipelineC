#pragma once

typedef struct eth_header_t
{
  uint48_t src_mac;
  uint48_t dst_mac;
  uint16_t ethertype;
} eth_header_t;
DECL_STREAM_TYPE(eth_header_t)

#define MAC_LEN 6
#define ETHERTYPE_LEN 2
