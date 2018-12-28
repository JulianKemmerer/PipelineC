#include "uintN_t.h"

#define elem_t uint8_t
#define DEPTH 128
#define addr_t uint7_t

elem_t ram[DEPTH];
elem_t main(addr_t addr, elem_t wd, uint1_t we)
{
	// One less place to change things if RAM specifier is in func name only?
	// How hard would it be to change? Alot of code would be the same
	// Justify justify 
	return ram_RAM_SP_RF(addr, wd, we);
}


/*
Single-Port RAM in Read-First Mode
Single-Port RAM in Write-First Mode
Dual-Port RW+R RAM
Dual-Port Block RAM With Two Write Ports
 
 Block rams are inferred by the tool - must be inferred from VHDL
 Dont manually encode, dont set bram inference in PipelineC, let tool settings/defaults do that
 
  
*/


