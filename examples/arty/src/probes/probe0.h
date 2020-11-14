#pragma once

// TODO better macro usage
#define probe0_t                app_debug_t
#define PROBE0_SIZE             app_debug_t_SIZE
#define probe0_size_t           app_debug_t_size_t
#define probe0_bytes_to_type    bytes_to_app_debug_t
#define probe0_type_to_bytes    app_debug_t_to_bytes
#define probe0_t_bytes_t        app_debug_t_bytes_t
#define probe0_t_array_1_t      app_debug_t_array_1_t
#define probe0_print(p)\
printf("PROBE0: ");\
printf("state,test_addr,test_data\n"); \
for(int i=0; i<DEBUG_SAMPLES; i+=1) \
{ \
  /* state */ \
  if(p.state[i]==WAIT_RESET) printf("WAIT_RESET");\
  if(p.state[i]==WRITES) printf("WRITES");\
  if(p.state[i]==READ_REQ) printf("READ_REQ");\
  if(p.state[i]==READ_RESP) printf("READ_RESP");\
  if(p.state[i]==FAILED) printf("FAILED");\
  printf(","); \
  /* test_addr */ \
  printf("%d,", p.test_addr[i]);\
  /* test_data */ \
  printf("%d\n", p.test_data[i]);\
}
#pragma MAIN_MHZ probe0_process xil_mig_module // Same clk as app
