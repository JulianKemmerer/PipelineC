#include "intN_t.h"
#include "uintN_t.h"
#include "compiler.h"
#include "stream/stream.h"
#pragma PART "xc7a35ticsg324-1l"

typedef struct my_struct_t{
  uint32_t x;
  uint32_t y;
}my_struct_t;
DECL_STREAM_TYPE(my_struct_t)
DECL_STREAM_TYPE(uint32_t)
uint32_t divider(my_struct_t i){
  return i.x / i.y;
}

// TODO MAKE #include "mcp.h" for macros like 
// GLOBAL_VALID_READY_MCP_INST(inst_name, out_type, func_name, in_type, NCYCLES)
#define inst_name mcp_divider
#define out_type uint32_t
#define func_name divider
#define in_type my_struct_t
#define NCYCLES 16

typedef struct PPCAT(PPCAT(PPCAT(func_name,_mcp),NCYCLES),_t){
  stream(out_type) stream_out;
  uint1_t ready_for_stream_in;
}PPCAT(PPCAT(PPCAT(func_name,_mcp),NCYCLES),_t);
PPCAT(PPCAT(PPCAT(func_name,_mcp),NCYCLES),_t) PPCAT(PPCAT(func_name,_mcp),NCYCLES)(
  stream(in_type) stream_in,
  uint1_t ready_for_stream_out
){
  // Start and capture regs for mcp
  PRAGMA_MESSAGE(MULTI_CYCLE NCYCLES launch capture)
  static in_type launch;
  static out_type capture;
  out_type capture_next = func_name(launch);
  // FSM logic exposing valid ready interface
  PPCAT(PPCAT(PPCAT(func_name,_mcp),NCYCLES),_t) o;
  o.stream_out.data = capture;
  static uint8_t cycles_since_launch;
  // Output side first for same cycle output and input handshake
  if(cycles_since_launch==NCYCLES){
    o.stream_out.valid = 1;
    if(o.stream_out.valid & ready_for_stream_out){
      cycles_since_launch = 0;
    }
  }else{
    cycles_since_launch += 1;
  }
  if(cycles_since_launch==0){
    o.ready_for_stream_in = 1;
    if(stream_in.valid & o.ready_for_stream_in){
      launch = stream_in.data;
      cycles_since_launch = 1;
    }
  }
  capture = capture_next;
  return o;
}

stream(in_type) PPCAT(inst_name,_in);
uint1_t PPCAT(inst_name,_in_ready);
stream(out_type) PPCAT(inst_name,_out);
uint1_t PPCAT(inst_name,_out_ready);
MAIN(inst_name)
void inst_name(){
  PPCAT(PPCAT(PPCAT(func_name,_mcp),NCYCLES),_t) f = PPCAT(PPCAT(func_name,_mcp),NCYCLES)(
     PPCAT(inst_name,_in),
     PPCAT(inst_name,_out_ready)
  );
  PPCAT(inst_name,_out) = f.stream_out;
  PPCAT(inst_name,_in_ready) = f.ready_for_stream_in;
}

#pragma MAIN_MHZ main 100
#pragma FUNC_MARK_DEBUG main
uint1_t main(){
  // FSM to test divider
  static uint32_t x = 2;
  static uint32_t y = 1;
  static uint32_t result;
  mcp_divider_in.data.x = x;
  mcp_divider_in.data.y = y;
  mcp_divider_in.valid = 1;
  if(mcp_divider_in_ready){
    printf("Divider in %d/%d\n", x, y);
    x += 2;
    y += 1;
    if(x==0){
      x = 2;
      y = 1;
    }
  }
  mcp_divider_out_ready = 1;
  if(mcp_divider_out.valid){
    result = mcp_divider_out.data;
    printf("Divider out %d\n", result);
  }
  return mcp_divider_out.data==2;
}