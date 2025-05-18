/* Thanks for the fantastic help from: 
https://github.com/agra-uni-bremen/microrv32/blob/master/microrv32/sw/basic-c/link.ld*/

OUTPUT_ARCH( "riscv" )
ENTRY(_bootstrap)

/* and Discord user dutracgi,
https://interrupt.memfault.com/blog/how-to-write-linker-scripts-for-firmware */

/* If see address errors/lockups: */
/*  check for missing sections not included in .data(ram) or .text(rom)*/
/*  try increasing the ram length, 16k didnt work */

/* Needs to match mem_map.h (TODO how to share variables?) */
MEMORY
{
  rom      (rx) : ORIGIN = 0x00000000, LENGTH = 512
  ram      (rw) : ORIGIN = 0x40000000, LENGTH = 2048
}

/* Section Definitions */
SECTIONS
{
    /* Top of ram for stack pointer (uninitialized/NOLOAD?)*/
    __stacktop = ORIGIN(ram) + LENGTH(ram);

    .text :
    {
        KEEP(*(.vectors .vectors.*))
        *(.text*)
    } > rom

    .data :
    {
        *(.data*)
        *(.sdata*) /* 's' small data */
        *(.rodata*) /* 'ro' read only data */
        *(.srodata*)
        *(.bss*) /* .bss section which is used for uninitialized data */
        *(.sbss*)
        *(.eh_frame*) /* exception handling, likely for float point */
        *(COMMON)
    } > ram AT >rom

    /* stack section 
    .stack (NOLOAD):
    {
        . = ALIGN(4);
        stack_begin = .;
        . = . + STACK_SIZE;
        . = ALIGN(4);
        stack_end = .;
    } > ram*/

    _end = . ;
}
