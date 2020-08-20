// Code wrapping the file (UART) interface to a common 'message'

// Thanks https://stackoverflow.com/questions/6947413/how-to-open-read-and-write-from-serial-port-in-c
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#include <fcntl.h> 
#include <string.h>
#include <termios.h>
#include <unistd.h>

// PipelineC header
#include "uart_msg.h"

int
set_interface_attribs (int fd, int speed, int parity)
{
        struct termios tty;
        if (tcgetattr (fd, &tty) != 0)
        {
                printf ("error %d from tcgetattr", errno);
                return -1;
        }

        cfsetospeed (&tty, speed);
        cfsetispeed (&tty, speed);

        tty.c_cflag = (tty.c_cflag & ~CSIZE) | CS8;     // 8-bit chars
        // disable IGNBRK for mismatched speed tests; otherwise receive break
        // as \000 chars
        tty.c_iflag &= ~IGNBRK;         // disable break processing
        tty.c_lflag = 0;                // no signaling chars, no echo,
                                        // no canonical processing
        tty.c_oflag = 0;                // no remapping, no delays
        tty.c_cc[VMIN]  = 0;            // read doesn't block
        tty.c_cc[VTIME] = 5;            // 0.5 seconds read timeout

        tty.c_iflag &= ~(IXON | IXOFF | IXANY | ICRNL); // shut off xon/xoff ctrl, no CR to NL,

        tty.c_cflag |= (CLOCAL | CREAD);// ignore modem controls,
                                        // enable reading
        tty.c_cflag &= ~(PARENB | PARODD);      // shut off parity
        tty.c_cflag |= parity;
        tty.c_cflag &= ~CSTOPB;
        tty.c_cflag &= ~CRTSCTS;

        if (tcsetattr (fd, TCSANOW, &tty) != 0)
        {
                printf ("error %d from tcsetattr", errno);
                return -1;
        }
        return 0;
}

void
set_blocking (int fd, int should_block)
{
        struct termios tty;
        memset (&tty, 0, sizeof tty);
        if (tcgetattr (fd, &tty) != 0)
        {
                printf ("error %d from tggetattr", errno);
                return;
        }

        tty.c_cc[VMIN]  = should_block ? 1 : 0;
        tty.c_cc[VTIME] = 5;            // 0.5 seconds read timeout

        if (tcsetattr (fd, TCSANOW, &tty) != 0)
                printf ("error %d setting term attributes", errno);
}


int uart_fd;
// Wrapper around msg init
int init_msgs()
{
  char *portname = "/dev/ttyUSB1";
  uart_fd = open (portname, O_RDWR | O_NOCTTY | O_SYNC);
  if (uart_fd < 0)
  {
    printf ("error %d opening %s: %s", errno, portname, strerror (errno));
    return -1;
  }

  set_interface_attribs (uart_fd, B115200, 0);  //B4800 B115200  B9600  set speed to 115,200 bps, 8n1 (no parity)
  printf("Baud: B115200 \n");
  set_blocking (uart_fd, 0);                // set blocking

  return 0;
}


// Wrapper around msg close
void close_msgs()
{
	// Close file descriptors
	if (uart_fd >= 0) {
			close(uart_fd);
	}
}

// Wrapper around uart write for this example
int msg_write(uart_msg_t* msg)
{
	uint8_t* buffer = &(msg->data[0]);
	size_t xfer_sz = MSG_SIZE;
  int pos = 0;
  int num_tries = 0;
  while((pos < MSG_SIZE) && (num_tries < 10))
  {
    int n = write(uart_fd, &(buffer[0+pos]), xfer_sz);
    xfer_sz -= n;
    pos += n;
    num_tries++;
  }
  if(pos != MSG_SIZE)
	{
		printf("Msg write failed, expected %d, got %d", MSG_SIZE, pos);
		exit(-1);
	}
  //usleep(MSG_SIZE * 100); // sleep approx 100 uS per char tx
  return 0;
}

// Wrapper around uart read for this example
int msg_read(uart_msg_t* msg)
{
  //usleep(MSG_SIZE * 100); // sleep approx 100 uS per char rx
	uint8_t* buffer = &(msg->data[0]);
	size_t xfer_sz = MSG_SIZE;
  int pos = 0;
  int num_zero = 0;
  while((pos < MSG_SIZE) && (num_zero < 20))
  {
    int n = read(uart_fd, &(buffer[0+pos]), xfer_sz);
    xfer_sz -= n;
    pos += n;
    num_zero += n == 0 ? 1 : 0;
  }
  if(pos != MSG_SIZE)
	{
		printf("Msg read failed, expected %d bytes, got %d\n", MSG_SIZE, pos);
		exit(-1);
	}
  return 0;
}


