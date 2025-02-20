// Code wrapping for read+writing UART file interface

#ifndef UART_TTY_DEVICE
#define UART_TTY_DEVICE "/dev/ttyUSB1"
#endif 

#ifndef UART_BAUD
#define UART_BAUD B115200
#endif

// Thanks https://stackoverflow.com/questions/6947413/how-to-open-read-and-write-from-serial-port-in-c
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <errno.h>
#include <fcntl.h> 
#include <string.h>
#include <termios.h>
#include <unistd.h>

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
// Wrapper around uart init
int init_uart()
{
  char *portname = UART_TTY_DEVICE;
  uart_fd = open (portname, O_RDWR | O_NOCTTY | O_SYNC);
  if (uart_fd < 0)
  {
    printf ("error %d opening %s: %s", errno, portname, strerror (errno));
    exit(-1);
  }

  set_interface_attribs (uart_fd, B115200, 0);  //B4800 B115200  B9600  set speed to 115,200 bps, 8n1 (no parity)
  //printf("Baud: B115200 \n");
  set_blocking (uart_fd, 0);                // set blocking

  return 0;
}


// Wrapper around uart close
void close_uart()
{
	// Close file descriptors
	if (uart_fd >= 0) {
			close(uart_fd);
	}
}

// Wrapper around uart file write for this example
int uart_write(uint8_t* buffer, size_t xfer_sz)
{
  size_t size = xfer_sz;
  int pos = 0;
  int num_tries = 0;
  while((pos < size) && (num_tries < 10))
  {
    int n = write(uart_fd, &(buffer[0+pos]), xfer_sz);
    xfer_sz -= n;
    pos += n;
    num_tries++;
  }
  if(pos != size)
	{
		printf("UART write failed, expected %ld, got %d\n", size, pos);
		exit(-1);
	}
  //usleep(MSG_SIZE * 100); // sleep approx 100 uS per char tx
  return 0;
}

// Wrapper around uart file read for this example
int uart_read(uint8_t* buffer, size_t xfer_sz)
{
  //usleep(MSG_SIZE * 100); // sleep approx 100 uS per char rx
	size_t size = xfer_sz;
  int pos = 0;
  int num_zero = 0;
  while((pos < size) && (num_zero < 20))
  {
    int n = read(uart_fd, &(buffer[0+pos]), xfer_sz);
    xfer_sz -= n;
    pos += n;
    num_zero += n == 0 ? 1 : 0;
  }
  if(pos != size)
	{
		printf("UART read failed, expected %ld bytes, got %d\n", size, pos);
		exit(-1);
	}
  return 0;
}


