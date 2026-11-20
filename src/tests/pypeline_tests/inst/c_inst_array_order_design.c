// Two INST_ARRAY write-side globals, each read by two MAINs: the top level's
// instance-array connections (VHDL.WRITE_MULTIMAIN_TOP) come out in an order
// that depends on PYTHONHASHSEED. Built by top_level_reader_order_test.py
// (known_issues_tests.py: c_inst_array_order_known_issue).
#include "uintN_t.h"
#define N_INSTS 2

uint32_t a_global;
uint32_t b_global;
#pragma MAIN writer0
void writer0(uint32_t i){ a_global = i; b_global = i + 1; }
#pragma MAIN writer1
void writer1(uint32_t i){ a_global = i; b_global = i + 2; }

uint32_t a_global_RD_AR[N_INSTS];
#pragma INST_ARRAY a_global a_global_RD_AR
uint32_t b_global_RD_AR[N_INSTS];
#pragma INST_ARRAY b_global b_global_RD_AR

#pragma MAIN reader0
uint32_t reader0(){ return a_global_RD_AR[0] + b_global_RD_AR[1]; }
#pragma MAIN reader1
uint32_t reader1(){ return a_global_RD_AR[1] + b_global_RD_AR[0]; }
