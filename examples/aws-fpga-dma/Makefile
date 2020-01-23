# Based on Amazon's cl_dram_dma example

INCLUDES = -I$(SDK_DIR)/userspace/include

CC = gcc
CFLAGS = -DCONFIG_LOGLEVEL=4 -std=gnu11 -g -Wall -Werror $(INCLUDES)

LDLIBS = -lfpga_mgmt

SRC = test.c
OBJ = $(SRC:.c=.o)

all: test $(BIN)

test: $(OBJ)
	$(CC) $(CFLAGS) -o test test.o test_dram_dma_common.o  $(LDFLAGS) $(LDLIBS)

clean:
	rm -f *.o test
