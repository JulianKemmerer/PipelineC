/* Thanks for the fantastic help from: 
https://github.com/agra-uni-bremen/microrv32/blob/master/microrv32/sw/basic-c/link.ld*/

OUTPUT_ARCH( "riscv" )
ENTRY(main) /*C code includes __attribute__ ((section(".text.init"))) on the main function*/

SECTIONS
{
  /* Place main func at address 0*/
  . = 0;
  .text.init : { *(.text.init) }
}


