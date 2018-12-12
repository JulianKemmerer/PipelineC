#include "uintN_t.h"

#define elem_t uint8_t
#define DEPTH 256
#define addr_t uint8_t

//#include "ram.h"
typedef elem_t elem_t_RAM_SP_RF;


elem_t_RAM_SP_RF ram[DEPTH];

elem_t ram_RAM(addr_t addr, elem_t wd, uint1_t we)
{
	// Dont have a construct for simultaneous read and write??
	// Uhh hows this?
	// Write is available next cycle?
	
	// DO read
	elem_t read;
	read = ram[addr];
	
	// D write
	elem_t data;
	// Default write current data
	data = read;
	if(we)
	{
		// Otherwise write new data
		data = wd;
	}
	// Write
	ram[addr] = data;
	
	
	return read;
}

elem_t main(addr_t addr, elem_t wd, uint1_t we)
{
	return ram_RAM(addr, wd, we);
}

/*
Single-Port RAM in Read-First Mode
Single-Port RAM in Write-First Mode
Dual-Port RW+R RAM
Dual-Port Block RAM With Two Write Ports
  
  Tag array defs with something
  
  RAM_SP_RF elem_t some_ram[N];
  // implies this global function exists - DEFAULTS to registers not BRAM so is implemented in PipelineC
  /*
  elem_t some_ram[N];
  elem_t some_ram_RAM(uint1_t we, addr_t addr, elem_t wd)
  * {
  * ...}
  
  
*/


