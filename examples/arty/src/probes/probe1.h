#pragma once

#define probe1_t                uint8_t
#define PROBE1_SIZE             uint8_t_SIZE
#define probe1_size_t           uint8_t_size_t
#define probe1_bytes_to_type    bytes_to_uint8_t
#define probe1_type_to_bytes    uint8_t_to_bytes
#define probe1_t_bytes_t        uint8_t_bytes_t
#define probe1_t_array_1_t      uint8_t_array_1_t
#pragma MAIN_MHZ probe1_process xil_mig_module // Same clk as app
#define probe1_print(p)\
printf("PROBE1: %d\n", p);
