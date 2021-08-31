#pragma once
#include "fosix_msg.h"

// Software specific packing and unpacking of bytes + helpers

// Bytes[1+] are specific to syscall

// Auto generated code for converting to and from bytes
#include "/home/julian/pipelinec_syn_output/type_array_N_t.h/uint8_t_array_N_t.h/uint8_t_array_N_t.h"
#include "/home/julian/pipelinec_syn_output/type_bytes_t.h/uint8_t_bytes_t.h/uint8_t_bytes.h"
#include "/home/julian/pipelinec_syn_output/type_bytes_t.h/uint32_t_bytes_t.h/uint32_t_bytes.h"
#include "/home/julian/pipelinec_syn_output/type_bytes_t.h/int32_t_bytes_t.h/int32_t_bytes.h"
// Requests
#include "/home/julian/pipelinec_syn_output/type_bytes_t.h/open_req_t_bytes_t.h/open_req_t_bytes.h"
#include "/home/julian/pipelinec_syn_output/type_bytes_t.h/write_req_t_bytes_t.h/write_req_t_bytes.h"
#include "/home/julian/pipelinec_syn_output/type_bytes_t.h/read_req_t_bytes_t.h/read_req_t_bytes.h"
#include "/home/julian/pipelinec_syn_output/type_bytes_t.h/close_req_t_bytes_t.h/close_req_t_bytes.h"
// Responses
#include "/home/julian/pipelinec_syn_output/type_bytes_t.h/open_resp_t_bytes_t.h/open_resp_t_bytes.h"
#include "/home/julian/pipelinec_syn_output/type_bytes_t.h/write_resp_t_bytes_t.h/write_resp_t_bytes.h"
#include "/home/julian/pipelinec_syn_output/type_bytes_t.h/read_resp_t_bytes_t.h/read_resp_t_bytes.h"
#include "/home/julian/pipelinec_syn_output/type_bytes_t.h/close_resp_t_bytes_t.h/close_resp_t_bytes.h"

// Process to system request
fosix_parsed_req_msg_t msg_to_request(fosix_msg_s msg_stream)
{
  fosix_msg_decoded_t decoded_msg = decode_msg(msg_stream);
  fosix_parsed_req_msg_t req;
  req.syscall_num = decoded_msg.syscall_num;
  bytes_to_open_req_t(decoded_msg.payload_data, &(req.sys_open));
  bytes_to_write_req_t(decoded_msg.payload_data, &(req.sys_write));
  bytes_to_read_req_t(decoded_msg.payload_data, &(req.sys_read));
  bytes_to_close_req_t(decoded_msg.payload_data, &(req.sys_close));
  return req;
}

// System to process response
fosix_msg_t response_to_msg(fosix_parsed_resp_msg_t resp)
{
  fosix_msg_t msg;
  if(resp.syscall_num == FOSIX_OPEN)
  {
    fosix_msg_decoded_t open_resp_msg;
    open_resp_msg.syscall_num = resp.syscall_num;
    open_resp_t_to_bytes(&resp.sys_open, open_resp_msg.payload_data);
    msg = decoded_msg_to_msg(open_resp_msg);
  }
  else if(resp.syscall_num == FOSIX_WRITE)
  {
    fosix_msg_decoded_t write_resp_msg;
    write_resp_msg.syscall_num = resp.syscall_num;
    write_resp_t_to_bytes(&resp.sys_write, write_resp_msg.payload_data);
    msg = decoded_msg_to_msg(write_resp_msg);
  }
  else if(resp.syscall_num == FOSIX_READ)
  {
    fosix_msg_decoded_t read_resp_msg;
    read_resp_msg.syscall_num = resp.syscall_num;
    read_resp_t_to_bytes(&resp.sys_read, read_resp_msg.payload_data);
    msg = decoded_msg_to_msg(read_resp_msg);
  }
  else if(resp.syscall_num == FOSIX_CLOSE)
  {
    fosix_msg_decoded_t close_resp_msg;
    close_resp_msg.syscall_num = resp.syscall_num;
    close_resp_t_to_bytes(&resp.sys_close, close_resp_msg.payload_data);
    msg = decoded_msg_to_msg(close_resp_msg);
  }
  
  return msg;
}
