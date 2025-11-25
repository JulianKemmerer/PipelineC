// TODO #include "ov_cam/ov_pmod_wires.c"
//        #include "sccb/sccb_wires.c"


#ifdef CAM_PIXEL_CLK_WIRE
#define CAM_PCLK_MHZ 26.0 // TODO thought was 25? Is 24? but call 26 to avoid confusing with other clocks, use clock group names
CLK_MHZ(cam_pixel_clk, CAM_PCLK_MHZ)
GLOBAL_IN_WIRE_CONNECT(uint1_t, cam_pixel_clk, CAM_PIXEL_CLK_WIRE)
MAIN_MHZ(cam_pixel_clk_connect, CAM_PCLK_MHZ) // TODO make all three macros into one?
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

#define CAM_SYS_CLK_MHZ 24 // TODO use VGA 25Mhz instead? or name with clock group to avoid confusion with pixel clock
CLK_MHZ(cam_sys_clk, CAM_SYS_CLK_MHZ)
#ifdef CAM_SYS_CLK_WIRE
DECL_INPUT(uint1_t, cam_sys_clk)
GLOBAL_OUT_WIRE_CONNECT(uint1_t, CAM_SYS_CLK_WIRE, cam_sys_clk)
MAIN_MHZ(PPCAT(CAM_SYS_CLK_WIRE,_connect), CAM_SYS_CLK_MHZ) // TODO make all three macros into one?
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