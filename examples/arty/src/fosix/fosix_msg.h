// Serializable protocol for fosix syscalls
// Hacky direct packing and unpacking from byte arrays for now
// (as opposed to stream parsing)

#pragma once
#include "uintN_t.h"
#include "fosix.h"

// Message to pass between C on host and PipelineC on FPGA

#define FOSIX_MSG_SIZE 64
#define fosix_msg_size_t uint7_t
#define FOSIX_PAYLOAD_SIZE 63 // Excluded 1 byte syscall_num_t uint8_t
typedef struct fosix_msg_t
{
  uint8_t data[FOSIX_MSG_SIZE];
} fosix_msg_t;
fosix_msg_t FOSIX_MSG_T_NULL()
{
  fosix_msg_t rv;
  fosix_msg_size_t i;
  for(i=0;i<FOSIX_MSG_SIZE;i=i+1)
  {
    rv.data[i] = 0;
  }
  return rv;
}

// Stream version of message with valid flag
typedef struct fosix_msg_s
{
  fosix_msg_t data; // The message
  uint1_t valid;
} fosix_msg_s;
fosix_msg_s FOSIX_MSG_S_NULL()
{
  fosix_msg_s rv;
  rv.data = FOSIX_MSG_T_NULL();
  rv.valid = 0;
  return rv;
}

// TODO Just use enums and casting?
// and also make msg stream func
// Byte[0] = Sycall ID

typedef struct fosix_msg_decoded_t
{
  syscall_num_t syscall_num;
  uint8_t payload_data[FOSIX_PAYLOAD_SIZE];
}fosix_msg_decoded_t;
fosix_msg_decoded_t FOSIX_MSG_DECODED_T_NULL()
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
  fosix_msg_decoded_t rv;
  
  // First byte is syscall num
  rv.syscall_num = FOSIX_UNKNOWN;
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

typedef struct fosix_proc_to_sys_t
{
  // Message
  fosix_msg_s msg;
  // And ready signal in opposite direction
  uint1_t sys_to_proc_msg_ready;
} fosix_proc_to_sys_t;
fosix_proc_to_sys_t POSIX_PROC_TO_SYS_T_NULL()
{
  fosix_proc_to_sys_t rv;
  rv.msg = FOSIX_MSG_S_NULL();
  rv.sys_to_proc_msg_ready = 0;
  return rv;
}

typedef struct fosix_sys_to_proc_t
{
  // Message
  fosix_msg_s msg;
  // And ready signal in opposite direction
  uint1_t proc_to_sys_msg_ready;
} fosix_sys_to_proc_t;
fosix_sys_to_proc_t POSIX_SYS_TO_PROC_T_NULL()
{
  fosix_sys_to_proc_t rv;
  rv.msg = FOSIX_MSG_S_NULL();
  rv.proc_to_sys_msg_ready = 0;
  return rv;
}

typedef struct fosix_parsed_req_msg_t
{
  syscall_num_t syscall_num; // use as valid+decode
	open_req_t sys_open;
	write_req_t sys_write;
  read_req_t sys_read;
  close_req_t sys_close;
} fosix_parsed_req_msg_t;

typedef struct fosix_parsed_resp_msg_t
{
  syscall_num_t syscall_num; // use as valid+decode
	open_resp_t sys_open;
	write_resp_t sys_write;
  read_resp_t sys_read;
  close_resp_t sys_close;
} fosix_parsed_resp_msg_t;

/*
// OPEN REQ
fosix_msg_t open_req_to_msg(open_req_t req)
{
  fosix_msg_t msg = FOSIX_MSG_T_NULL();
  msg = apply_syscall_id(FOSIX_OPEN, msg);
  
  // Bytes[1-(FOSIX_PATH_SIZE-1+1)] are path
  fosix_size_t i;
  for(i=1; i<(FOSIX_PATH_SIZE+1); i=i+1)
  {
    msg.data[i] = req.path[i-1];
  }
  
  return msg;
}
open_req_t msg_to_open_req(fosix_msg_t msg)
{
  open_req_t req;
  
  // Bytes[1-(FOSIX_PATH_SIZE-1+1)] are path
  fosix_size_t i;
  for(i=1; i<(FOSIX_PATH_SIZE+1); i=i+1)
  {
    req.path[i-1] = msg.data[i];
  }
  
  return req;
}
*/

// OPEN RESP
open_resp_t msg_to_open_resp(fosix_msg_t msg)
{
  open_resp_t resp;
  
  // Byte[1] = fildes
  resp.fildes = msg.data[1];
  
  return resp;
}
fosix_msg_t open_resp_to_msg(open_resp_t resp)
{
  fosix_msg_t msg = FOSIX_MSG_T_NULL();
  msg = apply_syscall_id(FOSIX_OPEN, msg);
  
  // Byte[1] = fildes
  msg.data[1] = resp.fildes;
  
  return msg;  
}

/*
// WRITE REQ
fosix_msg_t write_req_to_msg(write_req_t req)
{
  fosix_msg_t msg = FOSIX_MSG_T_NULL();
  msg = apply_syscall_id(FOSIX_WRITE, msg);
  
  // Byte[1] = fildes
  msg.data[1] = req.fildes;
  // Byte[2] = nbyte
  msg.data[2] = req.nbyte;
  // Byte[3-(FOSIX_BUF_SIZE-1+3)] = buf
  fosix_size_t i;
  for(i=3; i<(FOSIX_BUF_SIZE+3); i=i+1)
  {
    msg.data[i] = req.buf[i-3];
  }
  
  return msg;
}
write_req_t msg_to_write_req(fosix_msg_t msg)
{
  write_req_t req;
  
  // Byte[1] = fildes
  req.fildes = msg.data[1];
  // Byte[2] = nbyte
  req.nbyte = msg.data[2];
  // Byte[3-(FOSIX_BUF_SIZE-1+3)] = buf
  fosix_size_t i;
  for(i=3; i<(FOSIX_BUF_SIZE+3); i=i+1)
  {
    req.buf[i-3] = msg.data[i];
  }
  
  return req;
}
*/

// WRITE RESP
write_resp_t msg_to_write_resp(fosix_msg_t msg)
{
  write_resp_t resp;
  
  // Byte[1] = nbyte
  resp.nbyte = msg.data[1];
  
  return resp;
}
fosix_msg_t write_resp_to_msg(write_resp_t resp)
{
  fosix_msg_t msg = FOSIX_MSG_T_NULL();
  msg = apply_syscall_id(FOSIX_WRITE, msg);
  
  // Byte[1] = nbyte
  msg.data[1] = resp.nbyte;
  
  return msg;
}

/*
// READ REQ
fosix_msg_t read_req_to_msg(read_req_t req)
{
  fosix_msg_t msg = FOSIX_MSG_T_NULL();
  msg = apply_syscall_id(FOSIX_READ, msg);
  
  // Byte[1] = fildes
  msg.data[1] = req.fildes;
  // Byte[2] = nbyte
  msg.data[2] = req.nbyte;
  
  return msg;
}
read_req_t msg_to_read_req(fosix_msg_t msg) 
{
  read_req_t req;
  
  // Byte[1] = fildes
  req.fildes = msg.data[1];
  // Byte[2] = nbyte
  req.nbyte = msg.data[2];
  
  return req;
}
*/

// READ RESP
read_resp_t msg_to_read_resp(fosix_msg_t msg)
{
  read_resp_t resp;
  
  // Byte[1] = nbyte
  resp.nbyte = msg.data[1];
  // Byte[2-(FOSIX_BUF_SIZE-1+2)] = buf
  fosix_size_t i;
  for(i=2; i<(FOSIX_BUF_SIZE+2); i=i+1)
  {
    resp.buf[i-2] = msg.data[i];
  }
  
  return resp;
}
fosix_msg_t read_resp_to_msg(read_resp_t resp)
{
  fosix_msg_t msg = FOSIX_MSG_T_NULL();
  msg= apply_syscall_id(FOSIX_READ, msg);
  
  // Byte[1] = nbyte
  msg.data[1] = resp.nbyte;
  // Byte[2-(FOSIX_BUF_SIZE-1+2)] = buf
  fosix_size_t i;
  for(i=2; i<(FOSIX_BUF_SIZE+2); i=i+1)
  {
    msg.data[i] = resp.buf[i-2];
  }
  
  return msg;
}

/*
// CLOSE REQ
fosix_msg_t close_req_to_msg(close_req_t req)
{
  fosix_msg_t msg = FOSIX_MSG_T_NULL();
  msg = apply_syscall_id(FOSIX_CLOSE, msg);
  
  // Byte[1] = fildes
  msg.data[1] = req.fildes;
  
  return msg;
}
close_req_t msg_to_close_req(fosix_msg_t msg) 
{
  close_req_t req;
  
  // Byte[1] = fildes
  req.fildes = msg.data[1];
  
  return req;
}
*/

// CLOSE RESP
close_resp_t msg_to_close_resp(fosix_msg_t msg)
{
  close_resp_t resp;
  
  // Byte[1] = err
  resp.err = msg.data[1];
  
  return resp;
}
fosix_msg_t close_resp_to_msg(close_resp_t resp)
{
  fosix_msg_t msg = FOSIX_MSG_T_NULL();
  msg = apply_syscall_id(FOSIX_CLOSE, msg);
  
  // Byte[1] = err
  msg.data[1] = resp.err;
  
  return msg;
}
