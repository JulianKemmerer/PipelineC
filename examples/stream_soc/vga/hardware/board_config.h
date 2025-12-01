// Configure VGA module to use PMODs
// rgb is 8b internally, 4b on pmod
// PMOD JA
#define JA_0_OUT
#define JA_1_OUT
#define JA_2_OUT
#define JA_3_OUT
#define VGA_R0_WIRE pmod_ja_a_o1
#define VGA_R1_WIRE pmod_ja_a_o2 
#define VGA_R2_WIRE pmod_ja_a_o3 
#define VGA_R3_WIRE pmod_ja_a_o4 
#define JA_4_OUT
#define JA_5_OUT
#define JA_6_OUT
#define JA_7_OUT
#define VGA_B0_WIRE pmod_ja_b_o1 
#define VGA_B1_WIRE pmod_ja_b_o2 
#define VGA_B2_WIRE pmod_ja_b_o3 
#define VGA_B3_WIRE pmod_ja_b_o4 
// PMOD JB
#define JB_0_OUT
#define JB_1_OUT
#define JB_2_OUT
#define JB_3_OUT
#define VGA_G0_WIRE pmod_jb_a_o1 
#define VGA_G1_WIRE pmod_jb_a_o2 
#define VGA_G2_WIRE pmod_jb_a_o3
#define VGA_G3_WIRE pmod_jb_a_o4 
#define JB_4_OUT
#define JB_5_OUT
#define VGA_HS_WIRE pmod_jb_b_o1 
#define VGA_VS_WIRE pmod_jb_b_o2
// UNUSED FOR VGA PMOD #define JB_6_OUT
// UNUSED FOR VGA PMOD #define JB_7_OUT