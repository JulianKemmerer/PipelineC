# Based on Amazon's cl_dram_dma example

INCLUDES = -I$(SDK_DIR)/userspace/include

CC = gcc
CFLAGS = -DCONFIG_LOGLEVEL=4 -std=gnu11 -g -Wall -Werror $(INCLUDES)

LDLIBS = -lfpga_mgmt

SRC = work_test.c loopback_test.c small_msg_read_test.c
OBJ = $(SRC:.c=.o)

all: work_test loopback_test small_msg_read_test $(BIN)

work_test: $(OBJ)
	$(CC) $(CFLAGS) -o work_test work_test.o $(LDFLAGS) $(LDLIBS)

loopback_test: $(OBJ)
	$(CC) $(CFLAGS) -o loopback_test loopback_test.o $(LDFLAGS) $(LDLIBS)
	
small_msg_read_test: $(OBJ)
	$(CC) $(CFLAGS) -o small_msg_read_test small_msg_read_test.o $(LDFLAGS) $(LDLIBS)

clean:
	rm -f *.o work_test loopback_test small_msg_read_test
