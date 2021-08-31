// Serializable protocol for fosix syscalls
// Hacky direct packing and unpacking from byte arrays for now
// (as opposed to variable length stream parsing)

#pragma once
#include "uintN_t.h"
#include "fosix.h"

// Fixed size byte array message to pass between C on host and PipelineC on FPGA
#define FOSIX_MSG_SIZE 64
#define fosix_msg_size_t uint7_t
#define FOSIX_PAYLOAD_SIZE 63 // Excluded 1 byte syscall_num_t uint8_t
typedef struct fosix_msg_t
{
  uint8_t data[FOSIX_MSG_SIZE];
} fosix_msg_t;

// Stream version of message with valid flag
typedef struct fosix_msg_s
{
  fosix_msg_t data; // The message
  uint1_t valid;
} fosix_msg_s;

// Buses to and from 'processes' and the 'system'
typedef struct fosix_proc_to_sys_t
{
  // Message
  fosix_msg_s msg;
  // And ready signal in opposite direction
  uint1_t sys_to_proc_msg_ready;
} fosix_proc_to_sys_t;

typedef struct fosix_sys_to_proc_t
{
  // Message
  fosix_msg_s msg;
  // And ready signal in opposite direction
  uint1_t proc_to_sys_msg_ready;
} fosix_sys_to_proc_t;


// Byte[0] = Sycall ID
// Bytes[1+] are specific to syscall
typedef struct fosix_msg_decoded_t
{
  syscall_num_t syscall_num;
  uint8_t payload_data[FOSIX_PAYLOAD_SIZE];
}fosix_msg_decoded_t;
fosix_msg_decoded_t UNKNOWN_MSG()
{
  fosix_msg_decoded_t rv;
  rv.syscall_num = FOSIX_UNKNOWN;
  uint32_t i;
  for(i=0;i<FOSIX_PAYLOAD_SIZE;i=i+1)
  {
    rv.payload_data[i] = 0;
  }
  return rv;
}
fosix_msg_decoded_t decode_msg(fosix_msg_s msg_stream)
{
  fosix_msg_decoded_t rv = UNKNOWN_MSG();

  // First byte is syscall num
  //printf("msg.data[0] = %d\n",msg.data[0]);
  if(msg_stream.valid)
  {
    if(msg_stream.data.data[0]==FOSIX_READ)
    {
      rv.syscall_num = FOSIX_READ;
    }
    else if(msg_stream.data.data[0]==FOSIX_WRITE)
    {
      rv.syscall_num = FOSIX_WRITE;
    }
    else if(msg_stream.data.data[0]==FOSIX_OPEN)
    {
      rv.syscall_num = FOSIX_OPEN;
    }
    else if(msg_stream.data.data[0]==FOSIX_CLOSE)
    {
      rv.syscall_num = FOSIX_CLOSE;
    }
  }
  
  // Remaining bytes payload
  uint32_t i;
  for(i=0;i<FOSIX_PAYLOAD_SIZE;i+=1)
  {
    rv.payload_data[i] = msg_stream.data.data[i+1];
  }
    
  return rv;
}
fosix_msg_t decoded_msg_to_msg(fosix_msg_decoded_t decoded_msg)
{
  fosix_msg_t msg;
  msg.data[0] = decoded_msg.syscall_num;
  uint32_t i;
  for(i=0;i<FOSIX_PAYLOAD_SIZE;i+=1)
  {
    msg.data[i+1] = decoded_msg.payload_data[i];
  }
  return msg;
}
fosix_msg_t apply_syscall_id(syscall_num_t id, fosix_msg_t msg)
{
  msg.data[0] = id;
  return msg;
}
