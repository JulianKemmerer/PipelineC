#pragma once

#define XIL_MEM_MHZ 83.33 // UI CLK
#define XIL_MEM_ADDR_WIDTH 28
#define xil_mem_addr_t uint28_t
#define xil_mem_size_t uint29_t // Extra bit for counting over
#define XIL_MEM_SIZE 268435456 // 2^28 bytes , 256MB DDR3 = 28b address
#define XIL_MEM_32b_SIZE (XIL_MEM_SIZE/4) // Number of 32b words, 4 bytes each
#define XIL_MEM_ADDR_MAX (XIL_MEM_SIZE-1) //268435455 //4095 //268435455 // 2^28-1 // 256MB DDR3 = 28b address
