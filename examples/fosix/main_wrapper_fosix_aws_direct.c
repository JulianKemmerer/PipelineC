// Instantiate main
#pragma MAIN_MHZ main_wrapper 150.0
void main_wrapper(uint1_t rst)
{
  inputs_t i;
  outputs_t o;
  
  // Reads aws h2c going into main from fosix_aws_fpga_dma
  posix_h2c_t_array_1_t h2cs;
  h2cs = aws_h2c_READ();
  i.h2c = h2cs.data[0];
  
  o = main(i, rst);
  
  // Write aws c2h going out from main into fosix_aws_fpga_dma
  posix_c2h_t_array_1_t c2hs;
  c2hs.data[0] = o.c2h;
  aws_c2h_WRITE(c2hs);
}
