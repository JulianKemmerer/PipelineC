// Instantiate main
#pragma MAIN_MHZ main_wrapper 150.0
void main_wrapper(uint1_t rst)
{
  inputs_t i;
  outputs_t o;
  
  // Reads aws sys_to_proc going into main from fosix_aws_fpga_dma
  fosix_sys_to_proc_t_array_1_t sys_to_procs;
  sys_to_procs = aws_sys_to_proc_READ();
  i.sys_to_proc = sys_to_procs.data[0];
  
  o = main(i, rst);
  
  // Write aws proc_to_sys going out from main into fosix_aws_fpga_dma
  fosix_proc_to_sys_t_array_1_t proc_to_syss;
  proc_to_syss.data[0] = o.proc_to_sys;
  aws_proc_to_sys_WRITE(proc_to_syss);
}
