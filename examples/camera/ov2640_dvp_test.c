
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
// RGB LEDs
#define LED0_B_OUT
#define LED0_G_OUT
#define LED0_R_OUT
#include "board/arty.h"
//#include "i2s/i2s_regs.c"
//#include "vga/vga_wires_4b.c"
// TODO #include "ov_cam/ov_pmod_wires.c"
//        #include "sccb/sccb_wires.c"


#ifdef CAM_PIXEL_CLK_WIRE
#define CAM_PCLK_MHZ 25.0
CLK_MHZ(cam_pixel_clk, CAM_PCLK_MHZ)
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
// wait at least 3ms for sccb init
MAIN_MHZ(cam_por, CAM_SYS_CLK_MHZ)
uint1_t cam_reset_done;
void cam_por()
{
  static uint32_t counter;
  uint32_t ONE_SEC = CAM_SYS_CLK_MHZ*1000000;
  uint32_t THREE_MS = 3*(ONE_SEC/1000);
  cam_reset_done = counter==(THREE_MS-1);
  if(~cam_reset_done){
    counter += 1;
  }
}

// Timing params for SCCB
// TODO start/stop high/low times can likely be less than full bit periods
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
sccb_do_start_t sccb_do_start()
{
  static uint8_t sys_clk_counter;
  static uint2_t bit_counter;
  sccb_do_start_t o;

  // Drive outputs
  //   0123
  // C ---_
  // D --__
  if(bit_counter==0){
    o.sio_c = 1;
    o.sio_d_out = 1;
  }else if(bit_counter==1){
    o.sio_c = 1;
    o.sio_d_out = 1;
  }else if(bit_counter==2){
    o.sio_c = 1;
    o.sio_d_out = 0;
  }else if(bit_counter==3){
    o.sio_c = 0;
    o.sio_d_out = 0;
  }

  // Count up to bit time four times
  if(sys_clk_counter==(SCCB_SYS_CLKS_PER_BIT-1)){
    // Done all bits or next bit?
    sys_clk_counter = 0;
    if(bit_counter==3){
      // Done, reset when ready
      o.done = 1;
      bit_counter = 0;
    }else{
      // Next bit
      bit_counter = bit_counter + 1;
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
sccb_do_stop_t sccb_do_stop()
{
  static uint8_t sys_clk_counter;
  static uint2_t bit_counter; // bit counter
  sccb_do_stop_t o;

  // Drive outputs
  //   0123
  // C _---
  // D __--
  if(bit_counter==0){
    o.sio_c = 0;
    o.sio_d_out = 0;
  }else if(bit_counter==1){
    o.sio_c = 1;
    o.sio_d_out = 0;
  }else if(bit_counter==2){
    o.sio_c = 1;
    o.sio_d_out = 1;
  }else if(bit_counter==3){
    o.sio_c = 1;
    o.sio_d_out = 1;
  }

  // Count up to bit time four times
  if(sys_clk_counter==(SCCB_SYS_CLKS_PER_BIT-1)){
    // Done all bits or next bit?
    sys_clk_counter = 0;
    if(bit_counter==3){
      // Done, reset when ready
      o.done = 1;
      bit_counter = 0;
    }else{
      // Next bit
      bit_counter = bit_counter + 1;
    }
  }else{
    sys_clk_counter = sys_clk_counter + 1;
  }

  return o;
}


typedef enum sccb_do_write_data_state_t{
  INPUT_REG,
  DATA_BYTE,
  DONT_CARE_OR_ACK,
}sccb_do_write_data_state_t;
typedef struct sccb_do_write_data_t{
  uint1_t done;
  // Control of data pin
  uint1_t sio_d_out;
  uint1_t sio_d_out_enable;
}sccb_do_write_data_t;
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
  o.sio_d_out_enable = 1;

  if(state==INPUT_REG){
    UINT_TO_BIT_ARRAY(shift_reg, 8, input_data)
    bit_count = 0;
    state = DATA_BYTE;
  }
  // Pass through from input reg to start of data in same cycle

  if(state==DATA_BYTE){
    o.sio_d_out = shift_reg[7]; // MSB first
    o.sio_d_out_enable = 1;
    if(sio_d_clk_enable){
      ARRAY_SHIFT_UP(shift_reg, 8, 1)
      if(bit_count==7){
        state = DONT_CARE_OR_ACK;
      }else{
        bit_count = bit_count + 1;
      }
    }
  }else if(state==DONT_CARE_OR_ACK){
    o.sio_d_out = 0; // Dont care always zero? I2C expects 0?
    o.sio_d_out_enable = 0; // I2C says not driving here?
    if(sio_d_clk_enable){
      o.done = 1;
      state = INPUT_REG;
    }
  }

  return o;
}


typedef enum sccb_do_multi_phase_write_state_t{
  START,
  PHASES,
  STOP
}sccb_do_multi_phase_write_state_t;
typedef struct sccb_do_multi_phase_write_t{
  uint1_t done;
  // Control of pins
  uint1_t sio_d_out;
  uint1_t sio_d_out_enable;
  uint1_t sio_c;
}sccb_do_multi_phase_write_t;
sccb_do_multi_phase_write_t sccb_do_multi_phase_write(
  uint8_t phase_data[3],
  uint2_t num_phases
){
  sccb_do_multi_phase_write_t o;
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
  o.sio_d_out_enable = 1;
  // Toggle clock every half period
  if(sys_clk_counter==(SCCB_SYS_CLKS_PER_HALF_BIT-1)){
    sys_clk_counter = 0;
    sio_c_reg = ~sio_c_reg;
  }else{
    sys_clk_counter = sys_clk_counter + 1;
  }

  static sccb_do_multi_phase_write_state_t state;
  static uint2_t phase_count;
  if(state==START){
    sccb_do_start_t start_fsm = sccb_do_start();
    // Start FSM drives clock different than default free running
    o.sio_c = start_fsm.sio_c;
    o.sio_d_out = start_fsm.sio_d_out;
    o.sio_d_out_enable = 1; // start drives bus entire time
    if(start_fsm.done){
      // Data phases start in the middle of a clock low period
      sys_clk_counter = SCCB_SYS_CLKS_PER_QUARTER_BIT;
      sio_c_reg = 0;
      phase_count = 0;
      state = PHASES;
    }
  }else if(state==PHASES){
    // Do write fsm for current phase
    sccb_do_write_data_t write_fsm = sccb_do_write_data(phase_data[phase_count], d_out_change_now);
    o.sio_d_out = write_fsm.sio_d_out;
    o.sio_d_out_enable = write_fsm.sio_d_out_enable;
    if(write_fsm.done){
      if(phase_count==(num_phases-1)){
        state = STOP;
      }else{
        phase_count = phase_count + 1;
      }
    }
  }else if(state==STOP){
    sccb_do_stop_t stop_fsm = sccb_do_stop();
    // Stop FSM drives clock different than default free running
    o.sio_c = stop_fsm.sio_c;
    o.sio_d_out = stop_fsm.sio_d_out;
    o.sio_d_out_enable = 1; // stop drives bus entire time
    if(stop_fsm.done){
      o.done = 1;
      state = START;
    }
  }
  
  return o;
}


sccb_do_multi_phase_write_t sccb_do_write(
  uint7_t id,
  uint8_t addr,
  uint8_t data
){
  uint1_t is_read = 0;
  uint8_t phase_data[3] = {
    uint7_uint1(id, is_read),
    addr,
    data
  };
  return sccb_do_multi_phase_write(
    phase_data,
    3 // num phases
  );
}


typedef enum sccb_do_read_data_state_t{
  DATA_BYTE,
  WAIT_NA_START,
  NACK_BIT
}sccb_do_read_data_state_t;
typedef struct sccb_do_read_data_t{
  // Control of data pin
  uint1_t sio_d_out;
  uint1_t sio_d_out_enable;
  // IO handshakes
  uint8_t output_data;
  uint1_t output_valid; // aka done
}sccb_do_read_data_t;
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
      state = NACK_BIT;
    }
  }else if(state==NACK_BIT){
    // NACK bit drives 1 
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
    o.sio_d_out_enable = write_fsm.sio_d_out_enable;
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
sccb_do_read_t sccb_do_read(
  uint7_t id,
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
    uint8_t phase_data[3] = {
      uint7_uint1(id, is_read),
      addr,
      0 // unused write data
    };
    sccb_do_multi_phase_write_t write_fsm = sccb_do_multi_phase_write(phase_data, 2);
    o.sio_c = write_fsm.sio_c;
    o.sio_d_out = write_fsm.sio_d_out;
    o.sio_d_out_enable = write_fsm.sio_d_out_enable;
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
    uint8_t phase1_data = uint7_uint1(id, is_read);
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
sccb_ctrl_t sccb_ctrl(
  // IO handshakes
  uint7_t id,
  uint1_t is_read,
  uint8_t addr,
  uint8_t write_data,
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
  static uint7_t id_reg;
  static uint1_t is_read_reg;
  static uint8_t addr_reg;
  static uint8_t write_data_reg;
  static uint8_t read_data;
  o.output_read_data = read_data;

  if(state==INPUT_HANDSHAKE){
    o.ready_for_inputs = 1;
    if(inputs_valid){
      id_reg = id;
      is_read_reg = is_read;
      addr_reg = addr;
      write_data_reg = write_data;
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
      sccb_do_multi_phase_write_t write_fsm = sccb_do_write(id_reg, addr_reg, write_data_reg);
      o.sio_c = write_fsm.sio_c;
      o.sio_d_out = write_fsm.sio_d_out;
      o.sio_d_out_enable = write_fsm.sio_d_out_enable;
      if(write_fsm.done){
        state = OUTPUT_HANDSHAKE;
      }
    }
  }else if(state==OUTPUT_HANDSHAKE){
    o.output_valid = 1;
    if(ready_for_output){
      state = INPUT_HANDSHAKE;
    }
  }

  return o;
}


// OV2640 init over SCCB bus test
#include "leds/leds_port.c"
typedef enum cam_init_test_state_t{
  WAIT_RESET_DONE,
  CONFIG_WRITES,
  WAIT_SOFT_RESET_DONE,
  INIT_DONE
}cam_init_test_state_t;
uint1_t cam_init_done;
#pragma ASYNC_WIRE cam_init_done
MAIN_MHZ(cam_init_test, CAM_SYS_CLK_MHZ)
//#pragma FUNC_MARK_DEBUG cam_init_test
void cam_init_test(){
  // Default bus idle, not done
  sccb_sio_d_out = 1;
  sccb_sio_d_tristate_enable = 0;
  sccb_sio_c = 1;
  cam_init_done = 0;
  leds = 0;

  // Select the device using first 8b written to device
  //   Examples and app notes show D[7:0] = 0x60
  //   where D[0] is RW bit, write=0
  //   D[7:1] = 0x30 selects the device
  uint8_t write_device_id_with_rw = 0x60; // From app notes
  uint7_t id_7b_no_rw = write_device_id_with_rw >> 1; // drop RW bit

  // Init regs to write
  uint1_t is_read = 0;
  #define N_CONFIG_REGS 177
  uint16_t RESET_WRITE_INDEX = 1; // Soft reset write is second
  // TODO is delay after soft reset needed?
  static uint16_t num_writes;
  static uint8_t config_addr_value[N_CONFIG_REGS][2] = {
// 13.2 RGB 565 Reference Setting
// MCLK 24Mhz, SVGA RGB565 output 25fps
// Soft reset first...
{0xff, 0x01},
{0x12, 0x80},
//
{0xff, 0x00},
{0x2c, 0xff},
{0x2e, 0xdf},
{0xff, 0x01},
{0x3c, 0x32},
//
{0x11, 0x00},
{0x09, 0x02},
{0x04, 0x28},
{0x13, 0xe5},
{0x14, 0x48},
{0x2c, 0x0c},
{0x33, 0x78},
{0x3a, 0x33},
{0x3b, 0xfB},
//
{0x3e, 0x00},
{0x43, 0x11},
{0x16, 0x10},
//
{0x39, 0x92},
//
{0x35, 0xda},
{0x22, 0x1a},
{0x37, 0xc3},
{0x23, 0x00},
{0x34, 0xc0},
{0x36, 0x1a},
{0x06, 0x88},
{0x07, 0xc0},
{0x0d, 0x87},
{0x0e, 0x41},
{0x4c, 0x00},
{0x48, 0x00},
{0x5B, 0x00},
{0x42, 0x03},
//
{0x4a, 0x81},
{0x21, 0x99},
//
{0x24, 0x40},
{0x25, 0x38},
{0x26, 0x82},
{0x5c, 0x00},
{0x63, 0x00},
{0x46, 0x22},
{0x0c, 0x3c},
//
{0x61, 0x70},
{0x62, 0x80},
{0x7c, 0x05},
//
{0x20, 0x80},
{0x28, 0x30},
{0x6c, 0x00},
{0x6d, 0x80},
{0x6e, 0x00},
{0x70, 0x02},
{0x71, 0x94},
{0x73, 0xc1},
//
{0x12, 0x42}, // {0x12, 0x40}, // 0x42 enables colors bars too
{0x17, 0x11},
{0x18, 0x43},
{0x19, 0x00},
{0x1a, 0x4b},
{0x32, 0x09},
{0x37, 0xc0},
{0x4f, 0xca},
{0x50, 0xa8},
{0x5a, 0x23},
{0x6d, 0x00},
{0x3d, 0x38},
//
{0xff, 0x00},
{0xe5, 0x7f},
{0xf9, 0xc0},
{0x41, 0x24},
{0xe0, 0x14},
{0x76, 0xff},
{0x33, 0xa0},
{0x42, 0x20},
{0x43, 0x18},
{0x4c, 0x00},
{0x87, 0xd5},
{0x88, 0x3f},
{0xd7, 0x03},
{0xd9, 0x10},
{0xd3, 0x82},
//
{0xc8, 0x08},
{0xc9, 0x80},
//
{0x7c, 0x00},
{0x7d, 0x00},
{0x7c, 0x03},
{0x7d, 0x48},
{0x7d, 0x48},
{0x7c, 0x08},
{0x7d, 0x20},
{0x7d, 0x10},
{0x7d, 0x0e},
//
{0x90, 0x00},
{0x91, 0x0e},
{0x91, 0x1a},
{0x91, 0x31},
{0x91, 0x5a},
{0x91, 0x69},
{0x91, 0x75},
{0x91, 0x7e},
{0x91, 0x88},
{0x91, 0x8f},
{0x91, 0x96},
{0x91, 0xa3},
{0x91, 0xaf},
{0x91, 0xc4},
{0x91, 0xd7},
{0x91, 0xe8},
{0x91, 0x20},
//
{0x92, 0x00},
{0x93, 0x06},
{0x93, 0xe3},
{0x93, 0x05},
{0x93, 0x05},
{0x93, 0x00},
{0x93, 0x04},
{0x93, 0x00},
{0x93, 0x00},
{0x93, 0x00},
{0x93, 0x00},
{0x93, 0x00},
{0x93, 0x00},
{0x93, 0x00},
//
{0x96, 0x00},
{0x97, 0x08},
{0x97, 0x19},
{0x97, 0x02},
{0x97, 0x0c},
{0x97, 0x24},
{0x97, 0x30},
{0x97, 0x28},
{0x97, 0x26},
{0x97, 0x02},
{0x97, 0x98},
{0x97, 0x80},
{0x97, 0x00},
{0x97, 0x00},
//
{0xc3, 0xed},
{0xa4, 0x00},
{0xa8, 0x00},
{0xc5, 0x11},
{0xc6, 0x51},
{0xbf, 0x80},
{0xc7, 0x10},
{0xb6, 0x66},
{0xb8, 0xA5},
{0xb7, 0x64},
{0xb9, 0x7C},
{0xb3, 0xaf},
{0xb4, 0x97},
{0xb5, 0xFF},
{0xb0, 0xC5},
{0xb1, 0x94},
{0xb2, 0x0f},
{0xc4, 0x5c},
//
{0xc0, 0x64},
{0xc1, 0x4B},
{0x8c, 0x00},
{0x86, 0x3D},
{0x50, 0x00},
{0x51, 0xC8},
{0x52, 0x96},
{0x53, 0x00},
{0x54, 0x00},
{0x55, 0x00},
{0x5a, 0xC8},
{0x5b, 0x96},
{0x5c, 0x00},
{0xd3, 0x82},
//
{0xc3, 0xed},
{0x7f, 0x00},
//
{0xda, 0x08},
//
{0xe5, 0x1f},
{0xe1, 0x67},
{0xe0, 0x00},
{0xdd, 0x7f},
{0x05, 0x00}
  };

  // Init FSM
  static cam_init_test_state_t state;
  static uint16_t wait_counter;
  uint16_t WAIT_TIME = 125000;
  if(state==WAIT_RESET_DONE){
    leds = (uint4_t)1 << 0;
    if(cam_reset_done){
      state = CONFIG_WRITES;
    }
  }else if(state==CONFIG_WRITES){
    leds = (uint4_t)1 << 1;
    sccb_ctrl_t ctrl_fsm = sccb_ctrl(
      id_7b_no_rw, 
      is_read, 
      config_addr_value[0][0], 
      config_addr_value[0][1], 
      1, 
      1,
      sccb_sio_d_in
    );
    sccb_sio_d_out = ctrl_fsm.sio_d_out;
    sccb_sio_d_tristate_enable = ~ctrl_fsm.sio_d_out_enable;
    sccb_sio_c = ctrl_fsm.sio_c;
    if(ctrl_fsm.output_valid){
      // Last write?
      if(num_writes==(N_CONFIG_REGS-1)){
        state = INIT_DONE;
      }else{
        // Special write after soft reset?
        if(num_writes==RESET_WRITE_INDEX){
          state = WAIT_SOFT_RESET_DONE;
          wait_counter = 0;
        }
        // Prepare for next write
        num_writes = num_writes + 1;
        ARRAY_SHIFT_DOWN(config_addr_value, N_CONFIG_REGS, 1)
      }
    }
  }else if(state==WAIT_SOFT_RESET_DONE){
    leds = (uint4_t)1 << 2;
    if(wait_counter==WAIT_TIME){
      state = CONFIG_WRITES;
      wait_counter = 0;
    }else{
      wait_counter = wait_counter + 1;
    }
  }else if(state==INIT_DONE){
    leds = 0b1111;
    cam_init_done = 1;
  }
}

typedef enum dvp_rgb565_decoder_state_t{
  WAIT_VSYNC,
  WAIT_FRAME,
  OUTPUT_PIXELS
}dvp_rgb565_decoder_state_t;
typedef struct dvp_rgb565_decoder_t{
  uint5_t r;
  uint6_t g;
  uint5_t b;
  uint16_t x;
  uint16_t y;
  uint1_t pixel_valid;
  uint16_t width;
  uint16_t height;
  uint1_t frame_size_valid;
} dvp_rgb565_decoder_t;
#pragma FUNC_MARK_DEBUG dvp_rgb565_decoder
dvp_rgb565_decoder_t dvp_rgb565_decoder(
  uint1_t data[8],
  uint1_t href,
  uint1_t vsync,
  uint1_t vsync_pol,
  uint1_t cam_init_done
){
  dvp_rgb565_decoder_t o;

  // Assume vsync polarity is about idle inactive state?
  uint1_t vsync_active_level = ~vsync_pol;

  static uint16_t href_cycles_width; // width * 2
  o.width = href_cycles_width >> 1;
  static uint16_t href_cycles_counter; // x * 2
  o.x = href_cycles_counter >> 1;
  static uint16_t height;
  o.height = height;
  static uint16_t href_falling_edge_counter; // y
  o.y = href_falling_edge_counter;
  static uint1_t is_first_byte = 1;
  if(href){
    href_cycles_counter = href_cycles_counter + 1;
  }else{
    // href falling edge ends line
    if(href_cycles_counter > 0){ 
      href_cycles_width = href_cycles_counter;
      href_falling_edge_counter = href_falling_edge_counter + 1;
      href_cycles_counter = 0;
      is_first_byte = 1;
    }
  }
  // vsync transition to active level ends frame
  if(vsync==vsync_active_level){
    if(href_falling_edge_counter > 0){ 
      height = href_falling_edge_counter;
      href_falling_edge_counter = 0;
    }
  }

  static dvp_rgb565_decoder_state_t state;
  static uint1_t first_byte[8];
  static uint1_t second_byte[8];
  
  static uint1_t vs_reg;
  if(state==WAIT_VSYNC){
    // vsync transition from active to inactive level starts frame
    // Waits for cam init done too
    if((vsync==~vsync_active_level) & (vs_reg==vsync_active_level) & cam_init_done){
      state = WAIT_FRAME;
    }
    vs_reg = vsync;
  }else if(state==WAIT_FRAME){
    // vsync active ends frame
    if(vsync==vsync_active_level){
      state = OUTPUT_PIXELS;
    }
  }else if(state==OUTPUT_PIXELS){
    o.frame_size_valid = 1;
    if(href){
      if(is_first_byte){
        first_byte = data;
        is_first_byte = 0;
      }else{
        second_byte = data;
        o.pixel_valid = 1;
        is_first_byte = 1;
      }
      // RGB565 decode
      uint1_t r_bits[5];
      r_bits[4] = first_byte[7];
      r_bits[3] = first_byte[6];
      r_bits[2] = first_byte[5];
      r_bits[1] = first_byte[4];
      r_bits[0] = first_byte[3];
      o.r = uint1_array5_le(r_bits);
      uint1_t g_bits[6];
      g_bits[5] = first_byte[2];
      g_bits[4] = first_byte[1];
      g_bits[3] = first_byte[0];
      g_bits[2] = second_byte[7];
      g_bits[1] = second_byte[6];
      g_bits[0] = second_byte[5];
      o.g = uint1_array6_le(g_bits);
      uint1_t b_bits[5];
      b_bits[4] = second_byte[4];
      b_bits[3] = second_byte[3];
      b_bits[2] = second_byte[2];
      b_bits[1] = second_byte[1];
      b_bits[0] = second_byte[0];
      o.b = uint1_array5_le(b_bits);
    }
  }

  return o;
}


// Light RGB led based on pixel intensity
#include "cdc.h"
MAIN_MHZ(cam_pixel_test, CAM_PCLK_MHZ)
#pragma FUNC_MARK_DEBUG cam_pixel_test
void cam_pixel_test(){
  // Wait for cam init done, a signal from SCCB clock domain
  uint1_t init_done = xil_cdc2_bit(cam_init_done);

  // Assume VSYNC polarity is positive
  uint1_t vsync_pol = 1;

  // Decode pixel data from DVP 8bit bus
  uint1_t cam_data[8] = {
    cam_d0,
    cam_d1,
    cam_d2,
    cam_d3,
    cam_d4,
    cam_d5,
    cam_d6,
    cam_d7
  };
  dvp_rgb565_decoder_t decoder = dvp_rgb565_decoder(
    cam_data,
    cam_hr,
    cam_vs,
    vsync_pol,
    init_done
  );

  // Use pixel RGB intensity to light Arty RGB led
  static uint5_t r_counter;
  static uint6_t g_counter;
  static uint5_t b_counter;
  if(decoder.pixel_valid){
    led_r = (r_counter < decoder.r);
    led_g = (g_counter < decoder.g);
    led_b = (b_counter < decoder.b);
  }
  r_counter = r_counter + 1;
  g_counter = g_counter + 1;
  b_counter = b_counter + 1;

  // Debug registers
  static uint1_t cam_data_DEBUG[8];
  cam_data_DEBUG = cam_data;
  static uint1_t cam_href_DEBUG;
  cam_href_DEBUG = cam_hr;
  static uint1_t cam_vsync_DEBUG;
  cam_vsync_DEBUG = cam_vs;
  static dvp_rgb565_decoder_t decoder_DEBUG;
  decoder_DEBUG = decoder;
}
