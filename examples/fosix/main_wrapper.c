// Instantiate main
#pragma MAIN_MHZ main_wrapper 150.0
void main_wrapper()
{
  inputs_t i;
  outputs_t o;
  
  // Reads posix h2c going into main from posix_aws_fpga_dma
  posix_h2c_t_array_1_t h2cs;
  h2cs = posix_h2c_READ();
  i.posix_h2c = h2cs.data[0];
  
  o = main(i);
  
  // Write posix c2h going out from main into posix_aws_fpga_dma
  posix_c2h_t_array_1_t c2hs;
  c2hs.data[0] = o.posix_c2h;
  posix_c2h_WRITE(c2hs);
}
