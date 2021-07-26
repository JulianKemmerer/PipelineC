// Instantiate main
#pragma MAIN_MHZ main_wrapper 150.0
void main_wrapper(uint1_t rst)
{
  inputs_t i;
  outputs_t o;
  
  // Reads fosix sys_to_proc going into main from fosix
  fosix_sys_to_proc_t_array_1_t sys_to_procs;
  sys_to_procs = fosix_sys_to_proc_READ();
  i.sys_to_proc = sys_to_procs.data[0];
  
  o = main(i, rst);
  
  // Write fosix proc_to_sys going out from main into fosix
  fosix_proc_to_sys_t_array_1_t proc_to_syss;
  proc_to_syss.data[0] = o.proc_to_sys;
  fosix_proc_to_sys_WRITE(proc_to_syss);
}
