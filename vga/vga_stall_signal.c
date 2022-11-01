#pragma once

#define VGA_STALL_SIGNAL
// Wire to internal vga timing module
// that signals to stall/stop incrementing counters, etc
uint1_t vga_req_stall;