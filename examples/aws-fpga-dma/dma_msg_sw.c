// Code wrapping the file (XDMA driver) interface to a common 'DMA message'
// Based on AWS test_dram_dma.c example

// Standard libs
#include <stdio.h>
#include <fcntl.h>
#include <errno.h>
#include <string.h>
#include <stdlib.h>
#include <unistd.h>
#include <poll.h>
// AWS FPGA Libs
#include "fpga_pci.h"
#include "fpga_mgmt.h"
#include "fpga_dma.h"
#include "utils/lcd.h"
// AWS DMA helpers
#include "test_dram_dma_common.h"
// PipelineC header
#include "dma_msg.h"

// Wrapper around DMA init
int write_fd, read_fd;
int init_dma()
{
	// Return code (0=OK)
	int rc;

	/* initialize the fpga_plat library */
	rc = fpga_mgmt_init();
	fail_on(rc, out, "Unable to initialize the fpga_mgmt library");
	
	// Open write and read file descriptors
	write_fd = -1;
	read_fd = -1;
	int slot_id = 0;
	// Read 
	read_fd = fpga_dma_open_queue(FPGA_DMA_XDMA, slot_id,
			/*channel*/ 0, /*is_read*/ true);
	fail_on((rc = (read_fd < 0) ? -1 : 0), out, "unable to open read dma queue");
	// Write
	write_fd = fpga_dma_open_queue(FPGA_DMA_XDMA, slot_id,
			/*channel*/ 0, /*is_read*/ false);
	fail_on((rc = (write_fd < 0) ? -1 : 0), out, "unable to open write dma queue");
	
	return rc;
}

// Wrapper around DMA close
void close_dma()
{
	// Close file descriptors
	if (write_fd >= 0) {
			close(write_fd);
	}
	if (read_fd >= 0) {
			close(read_fd);
	}
}

// Wrapper around AWS fpga write for this example
int dma_write(dma_msg_t msg)
{
	uint8_t* buffer = &(msg.data);
	size_t xfer_sz = DMA_MSG_SIZE;
	size_t address = 0; // Write address ignored in hardware
	int rc = fpga_dma_burst_write(write_fd, buffer, xfer_sz, address);
  fail_on(rc, out, "DMA write failed");
  return rc;
}

// Wrapper around AWS fpga read for this example
dma_msg_t dma_read()
{
	dma_msg_t msg;
	uint8_t* buffer = &(msg.data);
	size_t xfer_sz = DMA_MSG_SIZE;
	size_t address = 0; // Read address ignored in hardware
	int rc = fpga_dma_burst_read(read_fd, buffer, buffer_size, address);
  fail_on(rc, out, "DMA read failed");
  return msg;
}


