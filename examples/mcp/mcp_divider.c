#include "intN_t.h"
#include "uintN_t.h"
#include "compiler.h"
#include "stream/stream.h"
#include "mcp.h"
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

GLOBAL_VALID_READY_MCP_INST(mcp_divider, uint32_t, divider, my_struct_t, 16)

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