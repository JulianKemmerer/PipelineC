#pragma once
#include "fosix_msg.h"

// Bytes[1+] are specific to syscall

// Auto generated code for converting to and from bytes
#include "/home/julian/pipelinec_syn_output/type_array_N_t.h/uint8_t_array_N_t.h/uint8_t_array_N_t.h"
#include "/home/julian/pipelinec_syn_output/type_bytes_t.h/uint8_t_bytes_t.h/uint8_t_bytes.h"
#include "/home/julian/pipelinec_syn_output/type_bytes_t.h/uint32_t_bytes_t.h/uint32_t_bytes.h"
#include "/home/julian/pipelinec_syn_output/type_bytes_t.h/int32_t_bytes_t.h/int32_t_bytes.h"
#include "/home/julian/pipelinec_syn_output/type_bytes_t.h/open_req_t_bytes_t.h/open_req_t_bytes.h"
#include "/home/julian/pipelinec_syn_output/type_bytes_t.h/write_req_t_bytes_t.h/write_req_t_bytes.h"
#include "/home/julian/pipelinec_syn_output/type_bytes_t.h/read_req_t_bytes_t.h/read_req_t_bytes.h"
#include "/home/julian/pipelinec_syn_output/type_bytes_t.h/close_req_t_bytes_t.h/close_req_t_bytes.h"

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
  fosix_msg_t msg = FOSIX_MSG_T_NULL();
  if(resp.syscall_num == FOSIX_OPEN)
  {
    msg = open_resp_to_msg(resp.sys_open);
  }
  else if(resp.syscall_num == FOSIX_WRITE)
  {
    msg = write_resp_to_msg(resp.sys_write);
  }
  else if(resp.syscall_num == FOSIX_READ)
  {
    msg = read_resp_to_msg(resp.sys_read);
  }
  else if(resp.syscall_num == FOSIX_CLOSE)
  {
    msg = close_resp_to_msg(resp.sys_close);
  }
  
  return msg;
}
fosix_parsed_resp_msg_t msg_to_response(fosix_msg_s msg_stream)
{
  fosix_parsed_resp_msg_t resp;
  fosix_msg_decoded_t decoded_msg = decode_msg(msg_stream);
  resp.syscall_num = decoded_msg.syscall_num;
  resp.sys_open  = msg_to_open_resp(msg_stream.data);
  resp.sys_write = msg_to_write_resp(msg_stream.data);
  resp.sys_read = msg_to_read_resp(msg_stream.data);
  resp.sys_close = msg_to_close_resp(msg_stream.data);
  return resp;
}


