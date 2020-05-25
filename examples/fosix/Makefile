# Based on Amazon's cl_dram_dma example

INCLUDES = -I$(SDK_DIR)/userspace/include

CC = gcc
CFLAGS = -DCONFIG_LOGLEVEL=4 -std=gnu11 -g -Wall -Werror $(INCLUDES)

LDLIBS = -lfpga_mgmt

SRC = host.c
OBJ = $(SRC:.c=.o)

all: host $(BIN)

host: $(OBJ)
	$(CC) $(CFLAGS) -o host host.o $(LDFLAGS) $(LDLIBS)

clean:
	rm -f *.o host
