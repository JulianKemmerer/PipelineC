# Based on Amazon's cl_dram_dma example

INCLUDES = -I$(SDK_DIR)/userspace/include

CC = gcc
CFLAGS = -DCONFIG_LOGLEVEL=4 -std=gnu11 -g -pthread -Wall -Werror $(INCLUDES)

LDLIBS = -lfpga_mgmt

SRC_WORK = work_test.c 
OBJ_WORK = $(SRC_WORK:.c=.o)

SRC_LOOP = loopback_test.c 
OBJ_LOOP= $(SRC_LOOP:.c=.o)

SRC_SMALL = small_msg_read_test.c 
OBJ_SMALL= $(SRC_SMALL:.c=.o)

SRC_LOOP_MT = loopback_test_multithread.c
OBJ_LOOP_MT = $(SRC_LOOP_MT:.c=.o)

all: work_test loopback_test small_msg_read_test $(BIN)

work_test: $(OBJ_WORK)
	$(CC) $(CFLAGS) -o work_test work_test.o $(LDFLAGS) $(LDLIBS)

loopback_test: $(OBJ_LOOP)
	$(CC) $(CFLAGS) -o loopback_test loopback_test.o $(LDFLAGS) $(LDLIBS)
	
small_msg_read_test: $(OBJ_SMALL)
	$(CC) $(CFLAGS) -o small_msg_read_test small_msg_read_test.o $(LDFLAGS) $(LDLIBS)
	
loopback_test: $(OBJ_LOOP_MT)
	$(CC) $(CFLAGS) -o loopback_test_multithread loopback_test_multithread.o $(LDFLAGS) $(LDLIBS)

clean:
	rm -f *.o work_test loopback_test small_msg_read_test loopback_test_multithread
