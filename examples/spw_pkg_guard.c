#include "uintN_t.h"

typedef enum spw_pkg_guard_state_t
{
  IDLE,
  FOPEN,
  PUMP,
  FCLOSE
}spw_pkg_guard_state_t;

#define DATA_WIDTH 9
typedef struct spw_pkg_guard_o_t
{
  uint1_t oHandshake;
  uint1_t oAck;
  uint1_t oValid;
  uint1_t oData[DATA_WIDTH];
} spw_pkg_guard_o_t;
#pragma MAIN spw_pkg_guard  // Is a single instance top level module with IO ports
spw_pkg_guard_o_t spw_pkg_guard(uint1_t iReset, uint1_t iHandshake, 
                                uint1_t iValid, uint1_t iData[DATA_WIDTH], uint1_t iAck)
{
    static spw_pkg_guard_state_t state; // static = reg
    spw_pkg_guard_o_t outputs;

    // TODO syntax const arrays `outputs.oData = 0;`
    // For loop needed to assign each elem of array
    uint32_t i = 0;
    
    // The FSM
    if(state == IDLE)
    {
      // State next
      if(iValid & (iData[8] == 0))
      {
        state = FOPEN;
      }
      // Outputs
      outputs.oHandshake = 0;
      outputs.oValid = 0;
      for(i=0;i<DATA_WIDTH;i+=1) outputs.oData[i] = 0;
      if(iValid & (iData[8] == 1))
      {
        outputs.oAck = 1;
      }  
      else
      {
        outputs.oAck = 0;
      }
    }
    else if(state == FOPEN)
    {
      // State next
      if(iHandshake)
      {
        state = PUMP;
      }
      // Outputs
      outputs.oHandshake = 1;
      outputs.oValid = 0;
      for(i=0;i<DATA_WIDTH;i+=1) outputs.oData[i] = 0;
      outputs.oAck = 0;
    }
    else if(state == PUMP)
    {
      // State next
      if(iValid & (iData[8] == 1) & iAck)
      {
        state = FCLOSE;
      }
      // Outputs
      outputs.oHandshake = 1;
      outputs.oValid = iValid;
      outputs.oData = iData;
      outputs.oAck = iAck;
    }
    else// if(state == FCLOSE)
    {
      // State next
      if(iHandshake == 0)
      {
        state = IDLE;
      }
      // Outputs
      outputs.oHandshake = 0;
      outputs.oValid = 0;
      for(i=0;i<DATA_WIDTH;i+=1) outputs.oData[i] = 0;
      outputs.oAck = 0;
    }
    
    
    if(iReset)
    {
      state = IDLE;
    }
    
    return outputs;
}
