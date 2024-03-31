
#pragma PART "xc7a100tcsg324-1"
#include "intN_t.h"
#include "uintN_t.h"
#include "examples/cordic.h"

typedef struct float2{
  float data[2];
}float2;

typedef struct float3{
  float data[3];
}float3;

/*```py
def unified(p0, p1, fi, T):
    #Input
    #P0 = [x, y]
    #P1 = [y, y]
    #FI = x
    #T = [x, y]
    #Returns
    #h = [
    #        [a, b, c],
    #        [d, e, f],
    #        [g, h, i]
    #    ]
    #b = [a, b, c]
    def u(p0, p1, fi, T):
        sin_fi = np.sin(fi)
        cos_fi = np.cos(fi)
        R = np.array((
            [cos_fi, -sin_fi],
            [sin_fi, cos_fi]
        ))
        sin_fi_p10 = sin_fi * p1[0]
        cos_fi_p11 = cos_fi * p1[1]
        cos_fi_p10 = cos_fi * p1[0]
        sin_fi_p11 = sin_fi * p1[1]
        n_sin_fi_p10_n_fi_p11 = -sin_fi_p10 - cos_fi_p11
        cos_fi_p10_n_sin_fi_p11 = cos_fi_p10 - sin_fi_p11

        p1_rotated = np.array([R[0,0]*p1[0]+R[0,1]*p1[1], R[1,0]*p1[0]+R[1,1]*p1[1]])
        e = np.array([p1_rotated[0]+T[0]-p0[0], p1_rotated[1]+T[1]-p0[1]])

        h = np.array([
            [1, 0, n_sin_fi_p10_n_fi_p11],
            [0, 1, cos_fi_p10_n_sin_fi_p11],
            [n_sin_fi_p10_n_fi_p11, cos_fi_p10_n_sin_fi_p11, n_sin_fi_p10_n_fi_p11**2 + cos_fi_p10_n_sin_fi_p11**2]
        ])
        b = np.array([e[0], e[1], n_sin_fi_p10_n_fi_p11*e[0]+cos_fi_p10_n_sin_fi_p11*e[1]])
        return h, b
    h, b = u(p0, p1, fi, T)
    return h, b
```*/

/*    #Input
    #P0 = [x, y]
    #P1 = [y, y]
    #FI = x
    #T = [x, y]
    #Returns
    #h = [
    #        [a, b, c],
    #        [d, e, f],
    #        [g, h, i]
    #    ]
    #b = [a, b, c]*/
//#pragma MAIN unified
typedef struct unified_out_t{
  float h[3][3];
  float3 b;
  uint1_t valid;
  uint32_t addr;
  uint1_t last;
}unified_out_t;
unified_out_t unified(
  float2 p0, float2 p1, float fi, float2 T,
  uint1_t valid,
  uint32_t addr,
  uint1_t last
){
  //float sin_fi = sin(fi);
  //float cos_fi = cos(fi);
  cordic_float_t cordic = cordic_float_fixed32_n32(fi);
  float sin_fi = cordic.s;
  float cos_fi = cordic.c;
  float R[2][2];
  R[0][0] = cos_fi;
  R[0][1] = -sin_fi;
  R[1][0] = sin_fi;
  R[1][1] = cos_fi;
  float sin_fi_p10 = sin_fi * p1.data[0];
  float cos_fi_p11 = cos_fi * p1.data[1];
  float cos_fi_p10 = cos_fi * p1.data[0];
  float sin_fi_p11 = sin_fi * p1.data[1];
  float n_sin_fi_p10_n_fi_p11 = -sin_fi_p10 - cos_fi_p11;
  float cos_fi_p10_n_sin_fi_p11 = cos_fi_p10 - sin_fi_p11;
  float p1_rotated[2];
  p1_rotated[0] = R[0][0]*p1.data[0]+R[0][1]*p1.data[1];
  p1_rotated[1] = R[1][0]*p1.data[0]+R[1][1]*p1.data[1];
  float e[2];
  e[0] = p1_rotated[0]+T.data[0]-p0.data[0];
  e[1] = p1_rotated[1]+T.data[1]-p0.data[1];
  unified_out_t rv;
  rv.last = last;
  rv.addr = addr;
  rv.valid = valid;
  rv.h[0][0] = 1.0;
  rv.h[0][1] = 0.0;
  rv.h[0][2] = n_sin_fi_p10_n_fi_p11;
  rv.h[1][0] = 0.0;
  rv.h[1][1] = 1.0;
  rv.h[1][2] = cos_fi_p10_n_sin_fi_p11;
  rv.h[2][0] = n_sin_fi_p10_n_fi_p11;
  rv.h[2][1] = cos_fi_p10_n_sin_fi_p11;
  rv.h[2][2] = (n_sin_fi_p10_n_fi_p11*n_sin_fi_p10_n_fi_p11) + (cos_fi_p10_n_sin_fi_p11*cos_fi_p10_n_sin_fi_p11);
  rv.b.data[0] = e[0];
  rv.b.data[1] = e[1];
  rv.b.data[2] = n_sin_fi_p10_n_fi_p11*e[0]+cos_fi_p10_n_sin_fi_p11*e[1];
  return rv;
}


#define N_POINTS 4
// TODO parameterize by N points at once read from RAM being processed instead of 1
// TODO RAM INIT VALUES

// Globally visible RAMs

// p0,p1
uint32_t p0p1_ram_in_addr;
uint1_t p0p1_ram_in_valid;
uint1_t p0p1_ram_in_last;
float2 p0_ram_out_data;
float2 p1_ram_out_data;
uint32_t p0p1_ram_out_addr;
uint1_t p0p1_ram_out_valid;
uint1_t p0p1_ram_out_last;
#pragma MAIN p0p1_ram_module
void p0p1_ram_module()
{
  // Most simple same cycle comb. logic implementation
  static float2 p0[N_POINTS];
  static float2 p1[N_POINTS];
  p0p1_ram_out_valid = p0p1_ram_in_valid;
  p0p1_ram_out_last = p0p1_ram_in_last;
  p0p1_ram_out_addr = p0p1_ram_in_addr;
  p0_ram_out_data = p0[p0p1_ram_in_addr];
  p1_ram_out_data = p1[p0p1_ram_in_addr];
}

// fi, T
uint32_t fit_ram_in_addr;
uint1_t fit_ram_in_valid;
uint1_t fit_ram_in_last;
uint1_t fit_ram_out_valid;
uint1_t fit_ram_out_last;
uint32_t fit_ram_out_addr;
float fi_ram_out_data;
float2 T_ram_out_data;
#pragma MAIN fit_ram_module
void fit_ram_module()
{
  // Most simple same cycle comb. logic implementation
  static float fi[N_POINTS];
  static float2 T[N_POINTS];
  fit_ram_out_valid = fit_ram_in_valid;
  fit_ram_out_last = fit_ram_in_last;
  fit_ram_out_addr = fit_ram_in_addr;
  fi_ram_out_data = fi[fit_ram_in_addr];
  T_ram_out_data = T[fit_ram_in_addr];
}

// Globally visible pipeline instances

// Unified pipeline
uint1_t unified_pipeline_in_valid;
uint32_t unified_pipeline_in_addr;
uint1_t unified_pipeline_in_last;
float2 unified_pipeline_in_p0;
float2 unified_pipeline_in_p1;
float unified_pipeline_in_fi;
float2 unified_pipeline_in_T;
unified_out_t unified_pipeline_out;
#pragma MAIN_MHZ unified_instance 50.0
void unified_instance()
{
  unified_pipeline_out = unified(
    unified_pipeline_in_p0, unified_pipeline_in_p1,
    unified_pipeline_in_fi, unified_pipeline_in_T,
    unified_pipeline_in_valid,
    unified_pipeline_in_addr,
    unified_pipeline_in_last
  );
}

// Globally visible instances

// H,B accumulator
unified_out_t hb_accum_in_data;
unified_out_t hb_accum_out_data;
uint1_t hb_accum_out_done;
#pragma MAIN hb_accum
void hb_accum()
{
  static unified_out_t out_reg;
  hb_accum_out_data = out_reg;
  hb_accum_out_done = out_reg.valid & out_reg.last;
  out_reg.valid = 0;
  if(hb_accum_in_data.valid){
    // Do accumulate // TODO right logic?
    uint32_t i;
    for (i = 0; i < 3; i+=1)
    {
      out_reg.b.data[i] += hb_accum_in_data.b.data[i];
      uint32_t j;
      for (j = 0; j < 3; j+=1)
      {
        out_reg.h[i][j] += hb_accum_in_data.h[i][j];
      }
    }
    if(hb_accum_in_data.last){
      out_reg.valid = 1;
      out_reg.last = 1;
    }
  }
}



typedef enum state_t{
  DO_UNIFIED,
  DONE
}state_t;
#pragma MAIN control_fsm
void control_fsm()
{
  // State regs
  static state_t state; // FSM state
  static uint32_t address; // For reading from RAMs
  static uint32_t cycle_counter; // For sim

  // Default no valid data flowing into anywhere
  p0p1_ram_in_valid = 0;
  fit_ram_in_valid = 0;
  unified_pipeline_in_valid = 0;
  hb_accum_in_data.valid = 0;

  // The state machine logic
  if(state==DO_UNIFIED)
  {
    // Stream many P0,P1,FI,T through unified pipeline into H,B accumulator
    // Simultaneously begin reads from P0P1 ram and FI,T RAM
    // Drive incrementing addr and read enable into rams
    uint1_t last = address==(N_POINTS-1);
    uint1_t valid = address<N_POINTS;
    p0p1_ram_in_addr = address;
    p0p1_ram_in_valid = valid;
    p0p1_ram_in_last = last;
    //
    fit_ram_in_addr = address;
    fit_ram_in_valid = valid;
    fit_ram_in_last = last;
    if(valid){
      printf("Cycle %d: Start read of P0,P1,FI,T [%d]...\n", cycle_counter, address); 
      address += 1;
    }

    // At the same time receive output from reads from RAM some cycles delayed
    // combine read stream into a unified pipeline input stream
    unified_pipeline_in_valid = p0p1_ram_out_valid & fit_ram_out_valid;
    unified_pipeline_in_addr = p0p1_ram_out_addr;
    unified_pipeline_in_last = p0p1_ram_out_last & fit_ram_out_last;
    unified_pipeline_in_p0 = p0_ram_out_data;
    unified_pipeline_in_p1 = p1_ram_out_data;
    unified_pipeline_in_fi = fi_ram_out_data;
    unified_pipeline_in_T = T_ram_out_data;
    if(p0p1_ram_out_valid){
      printf("Cycle %d: P0,P1,FI,T [%d] read data into unified pipeline...\n", cycle_counter, p0p1_ram_out_addr); 
    }

    // Outputs from unified pipeline flow into hb accum
    hb_accum_in_data.valid = unified_pipeline_out.valid;
    hb_accum_in_data.addr = unified_pipeline_out.addr;
    hb_accum_in_data.last = unified_pipeline_out.last;
    hb_accum_in_data.b = unified_pipeline_out.b;
    hb_accum_in_data.h = unified_pipeline_out.h;
    if(unified_pipeline_out.valid){
      printf("Cycle %d: unified pipeline output for P0,P1,FI,T [%d] into H,B accumulator...\n", cycle_counter, unified_pipeline_out.addr); 
    }

    // Last element out of unified pipeline produces accumulator done flag
    if(hb_accum_out_done){
      printf("Cycle %d: All points done. Result ready.\n", cycle_counter);
      state = DONE;
    }
  }

  cycle_counter += 1; // For sim printfs
}