/* Thanks for the fantastic help from: 
https://github.com/agra-uni-bremen/microrv32/blob/master/microrv32/sw/basic-c/link.ld*/

OUTPUT_ARCH( "riscv" )
ENTRY(_bootstrap)

SECTIONS
{
  /* Place entry point at address 0*/
  . = 0;
  .text.init : { *(.text.init) }
}


