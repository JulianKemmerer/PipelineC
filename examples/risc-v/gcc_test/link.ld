/* Thanks for the fantastic help from: 
https://github.com/agra-uni-bremen/microrv32/blob/master/microrv32/sw/basic-c/link.ld*/

OUTPUT_ARCH( "riscv" )
ENTRY(main)

/* With no sections listed with alignments, 
linker combines all into one rwx section it seems?
and get warning: main has a LOAD segment with RWX permissions
Work around for simple example with: --no-warn-rwx-segments*/

SECTIONS
{
  /* Try tp put main() at addr=0?
  . = 0;
  .text.init : { *(.text.init) }
  . = ALIGN(4);
  .text.postinit : { *(.text.postinit) }*/
}


