// Message to pass between C on host and PipelineC on FPGA

#pragma once
#include "../../../uintN_t.h"

// Try to match AWS, min 64 bytes, multiples of 64 bytes, max 4096
#define MSG_SIZE 8192 //4096 //16384
#define msg_size_t uint16_t
typedef struct msg_t
{
  uint8_t data[MSG_SIZE];
} msg_t;
msg_t MSG_T_NULL()
{
  msg_t rv;
  msg_size_t i;
  for(i=0;i<MSG_SIZE;i=i+1)
  {
    rv.data[i] = 0;
  }
  return rv;
}

// Stream version of message with valid flag
typedef struct msg_s
{
  msg_t data; // The message
  uint1_t valid;
} msg_s;
msg_s MSG_S_NULL()
{
  msg_s rv;
  rv.data = MSG_T_NULL();
  rv.valid = 0;
  return rv;
}
