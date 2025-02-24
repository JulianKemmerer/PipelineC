// gcc loopback_test.c -o loopback_test
// sudo ./loopback_test
#include <stdint.h> // for u/intN_t types
#include <unistd.h> // for close
#include <time.h> // Seed rand time
#include <math.h> // Rand nums

// 'Software' side of ethernet
#define DEFAULT_IF	"enx0050b6248f73" // Ethernet adapter name on host pc
#include "fpga_mac.h" // MAC address of the FPGA to talk to
#include "eth_sw.c"

// Init + do some work + close
int main(int argc, char **argv) 
{
	// Init eth to/from FPGA
	init_eth();
  
  // Do N times
	int n = 1;
  if(argc>1)
  {
    char *n_str = argv[1];
    n = atoi(n_str); 
  }
  srand(time(0));
  
  for(int i = 0; i < n; i++)
	{
    // Prepare random buffer
    uint8_t tx_payload[PAYLOAD_MAX];
    uint8_t rx_payload[PAYLOAD_MAX];
    size_t tx_payload_size = rand() % (PAYLOAD_MAX)+1;
    size_t rx_payload_size = 0;
    for(int b = 0; b < tx_payload_size; b++)
    {
      tx_payload[b] = rand();
    }
    
    // Send
    eth_write(tx_payload, tx_payload_size);
    // Receive
    eth_read(rx_payload, &rx_payload_size);
    // Compare
    // Fine to receive more data as long as it byte matches below
    if(rx_payload_size < tx_payload_size)
    {
      printf("i %d\n",i);
      printf("tx_payload_size %ld != %ld rx_payload_size\n",tx_payload_size,rx_payload_size); 
      exit(-1);
    }
    for(int b = 0; b < tx_payload_size; b++)
    {
      if(rx_payload[b] != tx_payload[b])
      {
        printf("i %d\n",i);
        printf("b %d\n",b);
        printf("rx_payload[b] %d !=  %d tx_payload[b]\n",rx_payload[b],tx_payload[b]); 
        exit(-1);
      }
    }
  }

  printf("Test passed!\n");
	// Close eth to/from FPGA
	close_eth();    
}

