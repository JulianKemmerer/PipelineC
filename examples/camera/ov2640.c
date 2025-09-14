
#include "uintN_t.h"
#include "intN_t.h"
#include "arrays.h"
#include "compiler.h"

// Arty FPGA
#pragma PART "xc7a100tcsg324-1"

// Configure PMOD Camera on Arty PMODS C+D
// https://www.tindie.com/products/johnnywu/pmod-camera-expansion-board
// PMOD JC
// NC #define JC_0_OUT
// #define NC pmod_jc_a_o1
#define JC_1_IN
#define CAM_PIXEL_CLK_WIRE pmod_jc_a_i2 
#define JC_2_IN
#define CAM_HR_WIRE pmod_jc_a_i3 
#define JC_3_OUT
#define SCCB_SIO_C_WIRE pmod_jc_a_o4 
// NC #define JC_4_OUT
// #define NC pmod_jc_b_o1 
#define JC_5_OUT
#define CAM_SYS_CLK_WIRE pmod_jc_b_o2 
#define JC_6_IN
#define CAM_VS_WIRE pmod_jc_b_i3
#define JC_7_INOUT
#define SCCB_SIO_D_I_WIRE pmod_jc_b_i4 
#define SCCB_SIO_D_O_WIRE pmod_jc_b_o4
#define SCCB_SIO_D_T_WIRE pmod_jc_b_t4 
// PMOD JD
#define JD_0_IN
#define CAM_D7_WIRE pmod_jd_a_i1 
#define JD_1_IN
#define CAM_D5_WIRE pmod_jd_a_i2 
#define JD_2_IN
#define CAM_D3_WIRE pmod_jd_a_i3
#define JD_3_IN
#define CAM_D1_WIRE pmod_jd_a_i4 
#define JD_4_IN
#define CAM_D6_WIRE pmod_jd_b_i1
#define JD_5_IN
#define CAM_D4_WIRE pmod_jd_b_i2 
#define JD_6_IN
#define CAM_D2_WIRE pmod_jd_b_i3 
#define JD_7_IN
#define CAM_D0_WIRE pmod_jd_b_i4 
#include "board/arty.h"
//#include "i2s/i2s_regs.c"
//#include "vga/vga_wires_4b.c"
// TODO #include "ov_cam/ov_pmod_wires.c"
//        #include "sccb/sccb_wires.c"


#ifdef CAM_PIXEL_CLK_WIRE
GLOBAL_IN_WIRE_CONNECT(uint1_t, cam_pixel_clk, CAM_PIXEL_CLK_WIRE)
#else
DECL_INPUT(uint1_t, cam_pixel_clk)
#endif

#ifdef CAM_HR_WIRE
GLOBAL_IN_REG_WIRE_CONNECT(uint1_t, cam_hr, CAM_HR_WIRE)
#else
DECL_INPUT_REG(uint1_t, cam_hr)
#endif

#ifdef SCCB_SIO_C_WIRE
GLOBAL_OUT_REG_WIRE_CONNECT(uint1_t, SCCB_SIO_C_WIRE, sccb_sio_c)
#else
DECL_OUTPUT_REG(uint1_t, sccb_sio_c)
#endif

#define CAM_SYS_CLK_MHZ 24
CLK_MHZ(cam_sys_clk, CAM_SYS_CLK_MHZ)
#ifdef CAM_SYS_CLK_WIRE
DECL_INPUT(uint1_t, cam_sys_clk)
GLOBAL_OUT_WIRE_CONNECT(uint1_t, CAM_SYS_CLK_WIRE, cam_sys_clk)
#else
DECL_OUTPUT(uint1_t, cam_sys_clk)
#endif

#ifdef CAM_VS_WIRE
GLOBAL_IN_REG_WIRE_CONNECT(uint1_t, cam_vs, CAM_VS_WIRE)
#else
DECL_INPUT_REG(uint1_t, cam_vs)
#endif

#ifdef SCCB_SIO_D_I_WIRE
GLOBAL_IN_REG_WIRE_CONNECT(uint1_t, sccb_sio_d_in, SCCB_SIO_D_I_WIRE)
#else
DECL_INPUT_REG(uint1_t, sccb_sio_d_in)
#endif

#ifdef SCCB_SIO_D_O_WIRE
GLOBAL_OUT_REG_WIRE_CONNECT(uint1_t, SCCB_SIO_D_O_WIRE, sccb_sio_d_out)
#else
DECL_OUTPUT_REG(uint1_t, sccb_sio_d_out)
#endif

#ifdef SCCB_SIO_D_T_WIRE
GLOBAL_OUT_REG_WIRE_CONNECT(uint1_t, SCCB_SIO_D_T_WIRE, sccb_sio_d_tristate_enable)
#else
DECL_OUTPUT_REG(uint1_t, sccb_sio_d_tristate_enable)
#endif

#ifdef CAM_D7_WIRE
GLOBAL_IN_REG_WIRE_CONNECT(uint1_t, cam_d7, CAM_D7_WIRE)
#else
DECL_INPUT_REG(uint1_t, cam_d7)
#endif

#ifdef CAM_D5_WIRE
GLOBAL_IN_REG_WIRE_CONNECT(uint1_t, cam_d5, CAM_D5_WIRE)
#else
DECL_INPUT_REG(uint1_t, cam_d5)
#endif

#ifdef CAM_D3_WIRE
GLOBAL_IN_REG_WIRE_CONNECT(uint1_t, cam_d3, CAM_D3_WIRE)
#else
DECL_INPUT_REG(uint1_t, cam_d3)
#endif

#ifdef CAM_D1_WIRE
GLOBAL_IN_REG_WIRE_CONNECT(uint1_t, cam_d1, CAM_D1_WIRE)
#else
DECL_INPUT_REG(uint1_t, cam_d1)
#endif

#ifdef CAM_D6_WIRE
GLOBAL_IN_REG_WIRE_CONNECT(uint1_t, cam_d6, CAM_D6_WIRE)
#else
DECL_INPUT_REG(uint1_t, cam_d6)
#endif

#ifdef CAM_D4_WIRE
GLOBAL_IN_REG_WIRE_CONNECT(uint1_t, cam_d4, CAM_D4_WIRE)
#else
DECL_INPUT_REG(uint1_t, cam_d4)
#endif

#ifdef CAM_D2_WIRE
GLOBAL_IN_REG_WIRE_CONNECT(uint1_t, cam_d2, CAM_D2_WIRE)
#else
DECL_INPUT_REG(uint1_t, cam_d2)
#endif

#ifdef CAM_D0_WIRE
GLOBAL_IN_REG_WIRE_CONNECT(uint1_t, cam_d0, CAM_D0_WIRE)
#else
DECL_INPUT_REG(uint1_t, cam_d0)
#endif


// Cam out of reset at power on
// wait at least 3ms for sccb init, be safe 10ms
// ...for debug delay for like 10sec prob...
MAIN_MHZ(cam_por, CAM_SYS_CLK_MHZ)
uint1_t cam_reset_done;
#pragma FUNC_MARK_DEBUG cam_por
void cam_por()
{
  static uint32_t counter;
  cam_reset_done = counter==(10*(CAM_SYS_CLK_MHZ*1000000));
  if(~cam_reset_done){
    counter += 1;
  }
}


#define SCCB_CLK_RATE_KHZ 100
#define SCCB_SYS_CLKS_PER_BIT ((CAM_SYS_CLK_MHZ*1000)/SCCB_CLK_RATE_KHZ)
#define SCCB_SYS_CLKS_PER_HALF_BIT (SCCB_SYS_CLKS_PER_BIT/2)
#define SCCB_SYS_CLKS_PER_QUARTER_BIT (SCCB_SYS_CLKS_PER_BIT/4)


typedef struct sccb_do_start_t{
  uint1_t done;
  // Control of data pins
  uint1_t sio_c;
  uint1_t sio_d_out;
}sccb_do_start_t;
#pragma FUNC_MARK_DEBUG sccb_do_start
sccb_do_start_t sccb_do_start()
{
  static uint8_t sys_clk_counter;
  static uint2_t q_counter; // quarter bit counter
  sccb_do_start_t o;

  // Drive outputs
  //   0123
  // C ---_
  // D --__
  if(q_counter==0){
    o.sio_c = 1;
    o.sio_d_out = 1;
  }else if(q_counter==1){
    o.sio_c = 1;
    o.sio_d_out = 1;
  }else if(q_counter==2){
    o.sio_c = 1;
    o.sio_d_out = 0;
  }else if(q_counter==3){
    o.sio_c = 0;
    o.sio_d_out = 0;
  }

  // Count up to quarter bit time four times
  if(sys_clk_counter==(SCCB_SYS_CLKS_PER_QUARTER_BIT-1)){
    // Done all quarters or next quarter bit?
    sys_clk_counter = 0;
    if(q_counter==3){
      // Done, reset when ready
      o.done = 1;
      q_counter = 0;
    }else{
      // Next quarter bit
      q_counter = q_counter + 1;
    }
  }else{
    sys_clk_counter = sys_clk_counter + 1;
  }

  return o;
}


typedef struct sccb_do_stop_t{
  uint1_t done;
  // Control of data pins
  uint1_t sio_c;
  uint1_t sio_d_out;
}sccb_do_stop_t;
#pragma FUNC_MARK_DEBUG sccb_do_stop
sccb_do_stop_t sccb_do_stop()
{
  static uint8_t sys_clk_counter;
  static uint2_t q_counter; // quarter bit counter
  sccb_do_stop_t o;

  // Drive outputs
  //   0123
  // C _---
  // D __--
  if(q_counter==0){
    o.sio_c = 0;
    o.sio_d_out = 0;
  }else if(q_counter==1){
    o.sio_c = 1;
    o.sio_d_out = 0;
  }else if(q_counter==2){
    o.sio_c = 1;
    o.sio_d_out = 1;
  }else if(q_counter==3){
    o.sio_c = 1;
    o.sio_d_out = 1;
  }

  // Count up to quarter bit time four times
  if(sys_clk_counter==(SCCB_SYS_CLKS_PER_QUARTER_BIT-1)){
    // Done all quarters or next quarter bit?
    sys_clk_counter = 0;
    if(q_counter==3){
      // Done, reset when ready
      o.done = 1;
      q_counter = 0;
    }else{
      // Next quarter bit
      q_counter = q_counter + 1;
    }
  }else{
    sys_clk_counter = sys_clk_counter + 1;
  }

  return o;
}


typedef enum sccb_do_write_data_state_t{
  INPUT_REG,
  DATA_BYTE,
  DONT_CARE,
}sccb_do_write_data_state_t;
typedef struct sccb_do_write_data_t{
  uint1_t done;
  // Control of data pin
  uint1_t sio_d_out;
}sccb_do_write_data_t;
#pragma FUNC_MARK_DEBUG sccb_do_write_data
sccb_do_write_data_t sccb_do_write_data(
  uint8_t input_data, // To write
  // Control of shift reg
  uint1_t sio_d_clk_enable // shift next bit onto output bus now (middle of sio_c low)
){
  static sccb_do_write_data_state_t state;
  static uint1_t shift_reg[8]; // data to shift out
  static uint3_t bit_count;

  sccb_do_write_data_t o; // outputs, default all zeros
  o.sio_d_out = 1; // Default IDLE high data

  if(state==INPUT_REG){
    UINT_TO_BIT_ARRAY(shift_reg, 8, input_data)
    bit_count = 0;
    state = DATA_BYTE;
  }
  // Pass through from input reg to start of data in same cycle

  if(state==DATA_BYTE){
    o.sio_d_out = shift_reg[7]; // MSB first
    if(sio_d_clk_enable){
      ARRAY_SHIFT_UP(shift_reg, 8, 1)
      if(bit_count==7){
        state = DONT_CARE;
      }else{
        bit_count = bit_count + 1;
      }
    }
  }else if(state==DONT_CARE){
    o.sio_d_out = 0; // Dont care always zero?
    if(sio_d_clk_enable){
      o.done = 1;
      state = INPUT_REG;
    }
  }

  return o;
}


typedef enum sccb_do_2phase_write_state_t{
  START,
  PHASES,
  STOP
}sccb_do_2phase_write_state_t;
typedef struct sccb_do_2phase_write_t{
  uint1_t done;
  // Control of pins
  uint1_t sio_d_out;
  uint1_t sio_c;
}sccb_do_2phase_write_t;
#pragma FUNC_MARK_DEBUG sccb_do_2phase_write
sccb_do_2phase_write_t sccb_do_2phase_write(
  uint8_t phase1_data,
  uint8_t phase2_data
){
  sccb_do_2phase_write_t o;
  // TODO make clock generator code into standalone module
  // SIO_C 'Clock' generator counts to half period time then toggles output
  // starts low, middle of low period is when output data should change
  // to be sampled during the middle of high period
  static uint8_t sys_clk_counter;
  static uint1_t sio_c_reg;
  // Dout clock enable to change reg is middle of low period
  uint1_t d_out_change_now = (sio_c_reg==0) & (sys_clk_counter==(SCCB_SYS_CLKS_PER_QUARTER_BIT-1));
  // During data clock is free running output from toggling reg
  o.sio_c = sio_c_reg;
  o.sio_d_out = 1; // Default high data
  // Toggle clock every half period
  if(sys_clk_counter==(SCCB_SYS_CLKS_PER_HALF_BIT-1)){
    sys_clk_counter = 0;
    sio_c_reg = ~sio_c_reg;
  }else{
    sys_clk_counter = sys_clk_counter + 1;
  }

  static sccb_do_2phase_write_state_t state;
  static uint1_t phase_count;
  if(state==START){
    sccb_do_start_t start_fsm = sccb_do_start();
    // Start FSM drives clock different than default free running
    o.sio_c = start_fsm.sio_c;
    o.sio_d_out = start_fsm.sio_d_out;
    if(start_fsm.done){
      // Data phases start in the middle of a clock low period
      sys_clk_counter = SCCB_SYS_CLKS_PER_QUARTER_BIT;
      sio_c_reg = 0;
      phase_count = 0;
      state = PHASES;
    }
  }else if(state==PHASES){
    // Do write fsm for current phase
    uint8_t phase_data = phase_count ? phase2_data : phase1_data;
    sccb_do_write_data_t write_fsm = sccb_do_write_data(phase_data, d_out_change_now);
    o.sio_d_out = write_fsm.sio_d_out;
    if(write_fsm.done){
      if(phase_count==1){
        state = STOP;
      }else{
        phase_count = 1;
      }
    }
  }else if(state==STOP){
    sccb_do_stop_t stop_fsm = sccb_do_stop();
    // Stop FSM drives clock different than default free running
    o.sio_c = stop_fsm.sio_c;
    o.sio_d_out = stop_fsm.sio_d_out;
    if(stop_fsm.done){
      o.done = 1;
      state = START;
    }
  }
  
  return o;
}


typedef enum sccb_do_read_data_state_t{
  DATA_BYTE,
  WAIT_NA_START,
  NA_BIT
}sccb_do_read_data_state_t;
typedef struct sccb_do_read_data_t{
  // Control of data pin
  uint1_t sio_d_out;
  uint1_t sio_d_out_enable;
  // IO handshakes
  uint8_t output_data;
  uint1_t output_valid; // aka done
}sccb_do_read_data_t;
#pragma FUNC_MARK_DEBUG sccb_do_read_data
sccb_do_read_data_t sccb_do_read_data(
  // Input data pin
  uint1_t sio_d_in,
  // Control when to sample and change output
  uint1_t sio_d_in_clk_enable, // sample bit from input bus now (middle of sio_c high)
  uint1_t sio_d_out_clk_enable // shift next bit onto output bus now (middle of sio_c low)
){
  static sccb_do_read_data_state_t state;
  static uint3_t bit_count;

  sccb_do_read_data_t o; // outputs, default all zeros
  // During most of read, sio_d is input, data is being not being driven onto sio_d
  o.sio_d_out_enable = 0;
  
  // Sampled data
  static uint1_t shift_reg[8];
  o.output_data = uint1_array8_le(shift_reg);

  if(state==DATA_BYTE){
    if(sio_d_in_clk_enable){
      ARRAY_1SHIFT_INTO_BOTTOM(shift_reg, 8, sio_d_in)
      if(bit_count==7){
        state = WAIT_NA_START;
      }else{
        bit_count = bit_count + 1;
      }
    }
  }else if(state==WAIT_NA_START){
    // Time before start of NA bit
    // second half of last data bit
    if(sio_d_out_clk_enable){
      state = NA_BIT;
    }
  }else if(state==NA_BIT){
    // NA bit drives 1
    o.sio_d_out = 1;
    o.sio_d_out_enable = 1;
    if(sio_d_out_clk_enable){
      // Done now
      o.output_valid = 1;
      state = DATA_BYTE;
      bit_count = 0;
    }
  }

  return o;
}


typedef enum sccb_do_2phase_read_state_t{
  START,
  WRITE_PHASE,
  READ_PHASE,
  STOP
}sccb_do_2phase_read_state_t;
typedef struct sccb_do_2phase_read_t{
  uint8_t output_data;
  uint1_t output_valid; //aka done
  // Control of pins
  uint1_t sio_d_out;
  uint1_t sio_d_out_enable;
  uint1_t sio_c;
}sccb_do_2phase_read_t;
#pragma FUNC_MARK_DEBUG sccb_do_2phase_read
sccb_do_2phase_read_t sccb_do_2phase_read(
  uint1_t sio_d_in,
  uint8_t write_data
){
  sccb_do_2phase_read_t o;
  // Default IDLE high data and high clock
  o.sio_d_out = 1;
  o.sio_d_out_enable = 1;
  o.sio_c = 1;

  // TODO make clock generator code into standalone module
  // SIO_C 'Clock' generator counts to half period time then toggles output
  // starts low, middle of low period is when output data should change
  // to be sampled during the middle of high period
  static uint8_t sys_clk_counter;
  static uint1_t sio_c_reg;
  // Dout clock enable to change reg is middle of low period
  uint1_t d_out_change_now = (sio_c_reg==0) & (sys_clk_counter==(SCCB_SYS_CLKS_PER_QUARTER_BIT-1));
  // Din sample is middle of high period
  uint1_t d_in_sample_now = (sio_c_reg==1) & (sys_clk_counter==(SCCB_SYS_CLKS_PER_QUARTER_BIT-1));
  // During data clock is free running output from toggling reg
  o.sio_c = sio_c_reg;
  // Toggle clock every half period
  if(sys_clk_counter==(SCCB_SYS_CLKS_PER_HALF_BIT-1)){
    sys_clk_counter = 0;
    sio_c_reg = ~sio_c_reg;
  }else{
    sys_clk_counter = sys_clk_counter + 1;
  }
  
  // Output read data from reg
  static uint8_t read_data;
  o.output_data = read_data;

  static sccb_do_2phase_read_state_t state;
  if(state==START){
    sccb_do_start_t start_fsm = sccb_do_start();
    // Start FSM drives clock different than default free running
    o.sio_c = start_fsm.sio_c;
    o.sio_d_out = start_fsm.sio_d_out;
    if(start_fsm.done){
      // Data phases start in the middle of a clock low period
      sys_clk_counter = SCCB_SYS_CLKS_PER_QUARTER_BIT;
      sio_c_reg = 0;
      state = PHASES;
    }
  }else if(state==WRITE_PHASE){
    // Do write phase fsm
    uint8_t phase_data = write_data;
    sccb_do_write_data_t write_fsm = sccb_do_write_data(phase_data, d_out_change_now);
    o.sio_d_out = write_fsm.sio_d_out;
    if(write_fsm.done){
      state = READ_PHASE;
    }
  }else if(state==READ_PHASE){
    // Do read phase fsm
    sccb_do_read_data_t read_fsm = sccb_do_read_data(sio_d_in, d_in_sample_now, d_out_change_now);
    o.sio_d_out = read_fsm.sio_d_out;
    o.sio_d_out_enable = read_fsm.sio_d_out_enable;    
    if(read_fsm.output_valid){
      read_data = read_fsm.output_data;
      state = STOP;
    }
  }else if(state==STOP){
    sccb_do_stop_t stop_fsm = sccb_do_stop();
    // Stop FSM drives clock different than default free running
    o.sio_c = stop_fsm.sio_c;
    o.sio_d_out = stop_fsm.sio_d_out;
    if(stop_fsm.done){
      o.output_valid = 1; // aka done
      state = START;
    }
  }
  
  return o;
}


typedef enum sccb_do_read_state_t{
  TWO_PHASE_WRITE,
  WRITE_IDLE_DELAY,
  TWO_PHASE_READ,
  READ_IDLE_DELAY,
}sccb_do_read_state_t;
typedef struct sccb_do_read_t{
  uint8_t output_data;
  uint1_t output_valid; //aka done
  // Output pins
  uint1_t sio_d_out;
  uint1_t sio_d_out_enable;
  uint1_t sio_c;
}sccb_do_read_t;
#pragma FUNC_MARK_DEBUG sccb_do_read
sccb_do_read_t sccb_do_read(
  uint8_t id,
  uint8_t addr,
  // Input data pin
  uint1_t sio_d_in
){
  sccb_do_read_t o;
  // Default high data and high clock for IDLE time
  o.sio_d_out = 1;
  o.sio_d_out_enable = 1;
  o.sio_c = 1;
  uint8_t IDLE_NUM_BITS = 4;
  static uint16_t sys_clk_counter;
  uint1_t idle_time_done = sys_clk_counter==((IDLE_NUM_BITS*SCCB_SYS_CLKS_PER_BIT)-1);
  sys_clk_counter = sys_clk_counter + 1;

  // Reg for read data output
  static uint8_t read_data;
  o.output_data = read_data;

  static sccb_do_read_state_t state;
  if(state==TWO_PHASE_WRITE){
    uint1_t is_read = 0;
    //uint8_t phase1_data = uint7_uint1(id, is_read);
    uint8_t phase1_data = uint7_uint1(id>>1, is_read);
    uint8_t phase2_data = addr;
    sccb_do_2phase_write_t write_fsm = sccb_do_2phase_write(phase1_data, phase2_data);
    o.sio_c = write_fsm.sio_c;
    o.sio_d_out = write_fsm.sio_d_out;
    o.sio_d_out_enable = 1; // write drives bus entire time
    if(write_fsm.done){
      state = WRITE_IDLE_DELAY;
      sys_clk_counter = 0;
    }
  }else if(state==WRITE_IDLE_DELAY){
    if(idle_time_done){
      state = TWO_PHASE_READ;
    }
  }else if(state==TWO_PHASE_READ){
    uint1_t is_read = 1;
    //uint8_t phase1_data = uint7_uint1(id, is_read);
    uint8_t phase1_data = uint7_uint1(id>>1, is_read);
    sccb_do_2phase_read_t read_fsm = sccb_do_2phase_read(sio_d_in, phase1_data);
    o.sio_c = read_fsm.sio_c;
    o.sio_d_out = read_fsm.sio_d_out;
    o.sio_d_out_enable = read_fsm.sio_d_out_enable;
    if(read_fsm.output_valid){
      read_data = read_fsm.output_data; 
      state = READ_IDLE_DELAY;
      sys_clk_counter = 0;
    } 
  }else if(state==READ_IDLE_DELAY){
    if(idle_time_done){
      o.output_valid = 1;
      state = TWO_PHASE_WRITE;
    }
  }

  return o;
}


typedef enum sccb_ctrl_state_t{
  INPUT_HANDSHAKE,
  READ_OR_WRITE,
  OUTPUT_HANDSHAKE
}sccb_ctrl_state_t;
typedef struct sccb_ctrl_t{
  // IO handshakes
  uint8_t output_read_data;
  uint1_t output_valid; // aka done
  uint1_t ready_for_inputs;
  // Output pins
  uint1_t sio_d_out;
  uint1_t sio_d_out_enable;
  uint1_t sio_c;
}sccb_ctrl_t;
#pragma FUNC_MARK_DEBUG sccb_ctrl
sccb_ctrl_t sccb_ctrl(
  // IO handshakes
  uint8_t id,
  uint1_t is_read,
  uint8_t addr,
  uint8_t write_data, // unused for now
  uint1_t inputs_valid, // aka start
  uint1_t ready_for_output,
  // Input data pin
  uint1_t sio_d_in
){
  sccb_ctrl_t o;
  // Default high data and high clock for IDLE time
  o.sio_d_out = 1;
  o.sio_d_out_enable = 1;
  o.sio_c = 1;
  static sccb_ctrl_state_t state;
  // IO regs for handshakes
  static uint8_t id_reg;
  static uint1_t is_read_reg;
  static uint8_t addr_reg;
  static uint8_t read_data;
  o.output_read_data = read_data;

  if(state==INPUT_HANDSHAKE){
    o.ready_for_inputs = 1;
    if(inputs_valid){
      id_reg = id;
      is_read_reg = is_read;
      addr_reg = addr;
      state = READ_OR_WRITE;
    }
  }else if(state==READ_OR_WRITE){
    if(is_read_reg){
      sccb_do_read_t read_fsm = sccb_do_read(id_reg, addr_reg, sio_d_in);
      o.sio_c = read_fsm.sio_c;
      o.sio_d_out = read_fsm.sio_d_out;
      o.sio_d_out_enable = read_fsm.sio_d_out_enable;
      if(read_fsm.output_valid){
        read_data = read_fsm.output_data;
        state = OUTPUT_HANDSHAKE;
      }
    }else{
      /* TODO sccb_do_write()
      sccb_do_write_t write_fsm = sccb_do_write(id_reg, addr_reg, write_data_reg sio_d_in);
      o.sio_c = write_fsm.sio_c;
      o.sio_d_out = write_fsm.sio_d_out;
      o.sio_d_out_enable = write_fsm.sio_d_out_enable;
      if(write_fsm.done){
        state = OUTPUT_HANDSHAKE;
      }*/
    }
  }else if(state==OUTPUT_HANDSHAKE){
    o.output_valid = 1;
    if(ready_for_output){
      state = INPUT_HANDSHAKE;
    }
  }

  return o;
}


// OV2640 SCCB bus test
// Light LEDs if read back of manufacturer ID works
#include "leds/leds_port.c"
typedef enum test_state_t{
  WAIT_RESET_DONE,
  DO_READ,
  LIGHT_LED
}test_state_t;
MAIN_MHZ(test, CAM_SYS_CLK_MHZ)
#pragma FUNC_MARK_DEBUG test
void test(){
  static test_state_t state;
  // Default lights off, bus idle
  leds = 0;
  sccb_sio_d_out = 1;
  sccb_sio_d_tristate_enable = 0;
  sccb_sio_c = 1;
  //uint8_t expected_pidh = 0x26;
  //static uint8_t pidh; // Actual received from cam
  static uint8_t bank;
  if(state==WAIT_RESET_DONE){
    leds = (uint4_t)1 << 0;
    if(cam_reset_done){
      state = DO_READ;
    }
  }else if(state==DO_READ){
    leds = (uint4_t)1 << 1;
    // Read the manufacturer ID from the OV2640 camera device
    uint8_t device_id = 0x60; // From app notes
    uint1_t is_read = 1;
    //uint8_t pidh_addr = 0x0A; // From datasheet
    uint8_t bank_addr = 0xFF;
    sccb_ctrl_t ctrl_fsm = sccb_ctrl(
      device_id, is_read, bank_addr, 0, 1, 1, sccb_sio_d_in
    );
    sccb_sio_d_out = ctrl_fsm.sio_d_out;
    sccb_sio_d_tristate_enable = ~ctrl_fsm.sio_d_out_enable;
    sccb_sio_c = ctrl_fsm.sio_c;
    if(ctrl_fsm.output_valid){
      bank = ctrl_fsm.output_read_data;
      state = LIGHT_LED;
    }
  }else if(state==LIGHT_LED){
    leds = (uint4_t)1 << 2;
    if(bank > 0){
      leds = 0b1111;
    }
  }

  static uint1_t sio_d_out_DEBUG;
  static uint1_t sio_d_in_DEBUG;
  static uint1_t sio_d_tri_DEBUG;
  static uint1_t sio_c_DEBUG;
  sio_d_out_DEBUG = sccb_sio_d_out;
  sio_d_in_DEBUG = sccb_sio_d_in;
  sio_d_tri_DEBUG = sccb_sio_d_tristate_enable;
  sio_c_DEBUG = sccb_sio_c;
}

