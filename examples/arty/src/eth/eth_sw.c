// Mostly taken from https://gist.github.com/austinmarton/

#include <arpa/inet.h>
#include <linux/if_packet.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <net/if.h>
#include <netinet/ether.h>

#include "fpga_mac.h"

#define DEFAULT_IF	"enx0050b6248f73"
#define BUF_SIZ		1024
#define PAYLOAD_MAX (BUF_SIZ-sizeof(struct ether_header))
#define ETHER_TYPE 0xFFFF

// interface info
char ifName[IFNAMSIZ];
// Write+read file//socket stuff
int write_sockfd;
struct ifreq write_if_idx;
struct ifreq write_if_mac;
struct sockaddr_ll write_socket_address = {0};
int read_sockfd;
struct ifreq read_if_idx;
struct ifreq read_if_mac;
struct sockaddr_ll read_socket_address = {0};
void init_eth()
{
	/* Set interface name */
  strcpy(ifName, DEFAULT_IF);

  // Open sending/writing file desriptor
	/* Open RAW socket to send on */
	if ((write_sockfd = socket(AF_PACKET, SOCK_RAW, IPPROTO_RAW)) == -1) {
	    perror("socket");
		exit(-1);
	}
	/* Get the index of the interface  */
	memset(&write_if_idx, 0, sizeof(struct ifreq));
	strncpy(write_if_idx.ifr_name, ifName, IFNAMSIZ-1);
	if (ioctl(write_sockfd, SIOCGIFINDEX, &write_if_idx) < 0)
	{
	    perror("SIOCGIFINDEX");
		exit(-1);
	}
	/* Get the MAC address of the interface  */
	memset(&write_if_mac, 0, sizeof(struct ifreq));
	strncpy(write_if_mac.ifr_name, ifName, IFNAMSIZ-1);
	if (ioctl(write_sockfd, SIOCGIFHWADDR, &write_if_mac) < 0)
	{
	   perror("SIOCGIFHWADDR");
	   exit(-1);
	}
  /* Index of the network device */
	write_socket_address.sll_ifindex = write_if_idx.ifr_ifindex;
	/* Address length*/
	write_socket_address.sll_halen = ETH_ALEN;
	/* Destination MAC */
	write_socket_address.sll_addr[0] = FPGA_MAC0;
	write_socket_address.sll_addr[1] = FPGA_MAC1;
	write_socket_address.sll_addr[2] = FPGA_MAC2;
	write_socket_address.sll_addr[3] = FPGA_MAC3;
	write_socket_address.sll_addr[4] = FPGA_MAC4;
	write_socket_address.sll_addr[5] = FPGA_MAC5;
	
  // Open receiving/reading file descriptor
	int sockopt;
	struct ifreq ifopts;	/* set promiscuous mode */
	/* Open PF_PACKET socket, listening for EtherType ETHER_TYPE */
	if ((read_sockfd = socket(PF_PACKET, SOCK_RAW, htons(ETHER_TYPE))) == -1) {
		perror("listener: socket");	
		exit(-1);
	}
  /* Get the index of the interface to send on */
	memset(&read_if_idx, 0, sizeof(struct ifreq));
	strncpy(read_if_idx.ifr_name, ifName, IFNAMSIZ-1);
	if (ioctl(read_sockfd, SIOCGIFINDEX, &read_if_idx) < 0)
	{
	    perror("SIOCGIFINDEX");
		exit(-1);
	}
  // Set the interface number for socket
  read_socket_address.sll_family = PF_PACKET;
  /* Index of the network device */
	read_socket_address.sll_ifindex = read_if_idx.ifr_ifindex;
  read_socket_address.sll_protocol = htons(ETHER_TYPE);
	//read_socket_address.sll_protocol = htons(ETH_P_ALL);
  /* Address length*/
	//read_socket_address.sll_halen = ETH_ALEN;
	/* Destination MAC */
	//read_socket_address.sll_addr[0] = MY_DEST_MAC0;
	//read_socket_address.sll_addr[1] = MY_DEST_MAC1;
	//read_socket_address.sll_addr[2] = MY_DEST_MAC2;
	//read_socket_address.sll_addr[3] = MY_DEST_MAC3;
	//read_socket_address.sll_addr[4] = MY_DEST_MAC4;
	//read_socket_address.sll_addr[5] = MY_DEST_MAC5;  
	/* Set interface to promiscuous mode - do we need to do this every time/at all?? */
	strncpy(ifopts.ifr_name, ifName, IFNAMSIZ-1);
	ioctl(read_sockfd, SIOCGIFFLAGS, &ifopts);
	ifopts.ifr_flags |= IFF_PROMISC;
	ioctl(read_sockfd, SIOCSIFFLAGS, &ifopts);
	/* Allow the socket to be reused - incase connection is closed prematurely */
	if (setsockopt(read_sockfd, SOL_SOCKET, SO_REUSEADDR, &sockopt, sizeof sockopt) == -1) {
		perror("setsockopt");
		close(read_sockfd);
		exit(EXIT_FAILURE);
	}
	/* Bind to device */
	/*if (setsockopt(read_sockfd, SOL_SOCKET, SO_BINDTODEVICE, ifName, IFNAMSIZ-1) == -1)	{
		perror("SO_BINDTODEVICE");
		close(read_sockfd);
		exit(EXIT_FAILURE);
	}*/
  if (bind(read_sockfd, (struct sockaddr*)&read_socket_address, sizeof(read_socket_address)) == -1) {
    perror("bind");
    exit(1);
  }
}

void close_eth()
{
  close(write_sockfd);
  close(read_sockfd);
}

void eth_read(uint8_t* payload_buf, size_t* payload_size)
{
  //printf("listener: Waiting to recvfrom...\n");
  ssize_t recv_size = BUF_SIZ;
  if(*payload_size < PAYLOAD_MAX && *payload_size > 0)
  {
    recv_size = sizeof(struct ether_header) + *payload_size;
  }
  uint8_t buf[BUF_SIZ];
  socklen_t address_len = sizeof(read_socket_address);
  ssize_t numbytes = 0;
  while(numbytes == 0)
  {
    numbytes = recvfrom(read_sockfd, buf, recv_size, 0, (struct sockaddr*)&read_socket_address, &address_len);
  }
  if(numbytes == -1)
  {
    perror("recvfrom");
  }
  //printf("listener: got packet %lu bytes\n", numbytes);

  /* Header structures */
  /*
	struct ether_header *eh = (struct ether_header *) buf;
  printf("SRC MAC: %x:%x:%x:%x:%x:%x\n",
						eh->ether_shost[0],
						eh->ether_shost[1],
						eh->ether_shost[2],
						eh->ether_shost[3],
						eh->ether_shost[4],
						eh->ether_shost[5]);
  printf("DST MAC: %x:%x:%x:%x:%x:%x\n",
						eh->ether_dhost[0],
						eh->ether_dhost[1],
						eh->ether_dhost[2],
						eh->ether_dhost[3],
						eh->ether_dhost[4],
						eh->ether_dhost[5]);*/

  // Copy into outputs
  *payload_size = numbytes - sizeof(struct ether_header);
  memcpy(payload_buf, &(buf[sizeof(struct ether_header)]), *payload_size);
  
  /* Print payload */
  /*printf("\tPayload Data:");
	for (i=sizeof(struct ether_header); i<numbytes; i++) printf("%02x:", buf[i]);
	printf("\n");*/
}

void eth_write(uint8_t* payload_buf, size_t payload_size)
{
  int tx_len = 0;
  char sendbuf[BUF_SIZ];
	struct ether_header *eh = (struct ether_header *) sendbuf;
  
  /* Construct the Ethernet frame */
	memset(sendbuf, 0, BUF_SIZ);
	/* Ethernet header */
	eh->ether_shost[0] = ((uint8_t *)&write_if_mac.ifr_hwaddr.sa_data)[0];
	eh->ether_shost[1] = ((uint8_t *)&write_if_mac.ifr_hwaddr.sa_data)[1];
	eh->ether_shost[2] = ((uint8_t *)&write_if_mac.ifr_hwaddr.sa_data)[2];
	eh->ether_shost[3] = ((uint8_t *)&write_if_mac.ifr_hwaddr.sa_data)[3];
	eh->ether_shost[4] = ((uint8_t *)&write_if_mac.ifr_hwaddr.sa_data)[4];
	eh->ether_shost[5] = ((uint8_t *)&write_if_mac.ifr_hwaddr.sa_data)[5];
	eh->ether_dhost[0] = FPGA_MAC0;
	eh->ether_dhost[1] = FPGA_MAC1;
	eh->ether_dhost[2] = FPGA_MAC2;
	eh->ether_dhost[3] = FPGA_MAC3;
	eh->ether_dhost[5] = FPGA_MAC5;
	eh->ether_dhost[4] = FPGA_MAC4;
	/* Ethertype field */
	eh->ether_type = htons(ETHER_TYPE);
	tx_len += sizeof(struct ether_header);

	/* Packet data */
  memcpy(&(sendbuf[tx_len]), payload_buf, payload_size);
  tx_len += payload_size;
 
  /* Send packet */
	if (sendto(write_sockfd, sendbuf, tx_len, 0, (struct sockaddr*)&write_socket_address, sizeof(struct sockaddr_ll)) < 0)
	    printf("Send failed\n");
}
