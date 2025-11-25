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
