#include "compiler.h"
#include "wire.h"
#include "../leds/led0_3.c"
#include "../uart/uart_msg_fifos.c"
#include "../ddr3/xil_mig.c"
#include "test.h" // Constants shared with software

// Write stream of messages from uart to DDR3, and once done
// read those same messages back from DDR3 stream out over uart

// State machine that waits for incoming message over uart (async fifos)
// Then writes it to DDR memory at a specific address
typedef enum uart_to_mem_state_t
{
  RESET,
  WAIT_MSG,
  SER_MSG,
}uart_to_mem_state_t;
typedef struct uart_to_mem_t
{
  uint1_t ready;
  xil_app_to_mig_t to_mem;
  uint1_t done; 
}uart_to_mem_t;
uart_to_mem_t uart_to_mem(uint1_t start, test_count_t msg_index, xil_mig_to_app_t from_mem)
{
  // Registers
  static uart_to_mem_state_t state; // FSM state
  static uart_msg_t msg; // Message from uart / memory deserializer buffer
  
  // Outputs
  uart_to_mem_t o;
  o.to_mem = XIL_APP_TO_MIG_T_NULL();
  o.done = 0;
  o.ready = 0;
  
  if(state==RESET)
  {
    o.ready = 1;
    if(start)
    {
      state = WAIT_MSG;
    }
  }
  else if(state==WAIT_MSG)
  {
    // Wait for valid message from uart
    uart_rx_msg_fifo_receiver_t msg_rx = uart_rx_msg_fifo_receiver(1);
    if(msg_rx.done)
    {
      // Then begin serializing it
      msg = msg_rx.msg;
      state = SER_MSG;
    }
  }
  else if(state==SER_MSG)
  {
    // Begin ddr serializer 
    xil_mig_addr_t byte_addr = UART_MSG_SIZE_MULT(msg_index);
    mig_write_256_t ser = mig_write_256(1, byte_addr, msg.data, from_mem);
    o.to_mem = ser.to_mem;
    msg.data = ser.data;
    // Wait until serializer done
    if(ser.done)
    {
      // Then all the way done, back to start
      o.done = 1;
      state = RESET;
    }
  }
  
  return o;
}

// State machine controlling memory to read a message from a specific address
// and then waits for the message to be outgoing over uart (async fifo)
typedef enum mem_to_uart_state_t
{
  RESET,
  DESER_MSG,
  WAIT_MSG
}mem_to_uart_state_t;
typedef struct mem_to_uart_t
{
  uint1_t ready;
  xil_app_to_mig_t to_mem;
  uint1_t done; 
}mem_to_uart_t;
mem_to_uart_t mem_to_uart(uint1_t start, test_count_t msg_index, xil_mig_to_app_t from_mem)
{
  // Registers
  static mem_to_uart_state_t state; // FSM state
  static uart_msg_t msg; // Message from memory deserializer buffer / into uar
  
  // Drive leds
  WIRE_WRITE(uint1_t, led1, state==WAIT_MSG)
  
  // Outputs
  mem_to_uart_t o;
  o.to_mem = XIL_APP_TO_MIG_T_NULL();
  o.done = 0;
  o.ready = 0;
  
  if(state==RESET)
  {
    o.ready = 1;
    if(start)
    {
      state = DESER_MSG;
    }
  }
  else if(state==DESER_MSG)
  {
    // Begin ddr deserializer 
    xil_mig_addr_t byte_addr = UART_MSG_SIZE_MULT(msg_index);
    mig_read_256_t deser = mig_read_256(1, byte_addr, msg.data, from_mem);
    msg.data = deser.data;
    o.to_mem = deser.to_mem;
    // Wait until deserializer done and we have full message
    if(deser.done)
    {
      // Then wait until message goes out over uart
      state = WAIT_MSG;
    }
  }
  else if(state==WAIT_MSG)
  {
    // Begin trying to send msg out
    uart_tx_msg_fifo_sender_t msg_tx = uart_tx_msg_fifo_sender(1, msg);
    // Wait for message to go out over uart
    if(msg_tx.done)
    {
      // Then all the way done, back to start
      o.done = 1;
      state = RESET;
    }
  }
  
  return o;
}

// Uses above state machines to transfer messages to/from DDR memory
typedef enum msg_ctrl_state_t
{
  WAIT_RESET,
  UART_TO_MEM, // N messages into memory
  MEM_TO_UART // N messages out of memory
}msg_ctrl_state_t;
// The main process, same clock as generated memory interface
#pragma MAIN_MHZ app xil_mig_module
void app()
{
  // Input port: read outputs wires from memory controller
  xil_mig_to_app_t from_mem;
  WIRE_READ(xil_mig_to_app_t, from_mem, xil_mig_to_app)
  
  // Output port wire: into memory controller
  xil_app_to_mig_t to_mem = XIL_APP_TO_MIG_T_NULL();
  
  // Registers
  static msg_ctrl_state_t state;
  static test_count_t num_msgs;
  
  // Drive leds
  WIRE_WRITE(uint1_t, led0, state==MEM_TO_UART)

  // MEM CTRL FSM
  if(state==WAIT_RESET)
  {
    // Wait for DDR reset to be done
    uint1_t mem_rst_done = !from_mem.ui_clk_sync_rst & from_mem.init_calib_complete;
    if(mem_rst_done)
    {
      // Start things with writes first
      state = UART_TO_MEM;
    }
    num_msgs = 0;
  }
  else if(state==UART_TO_MEM)
  {
    // Keep starting the uart_to_mem fsm until N messages have been written to mem
    uart_to_mem_t writer = uart_to_mem(1, num_msgs, from_mem);
    to_mem = writer.to_mem;   
    if(writer.done)
    {
      // next message ?
      if(num_msgs<(NUM_MSGS_TEST-1))
      {
        // Do next message
        num_msgs += 1;
      }
      else
      {
        // Done writing messages, onto reads
        state = MEM_TO_UART;
        num_msgs = 0;
      }
    }
  }
  else if(state==MEM_TO_UART)
  {
    // Keep starting the mem_to_uart fsm until N messages have been read from mem
    mem_to_uart_t reader = mem_to_uart(1, num_msgs, from_mem);
    to_mem = reader.to_mem;
    if(reader.done)
    {
      // next message ?
      if(num_msgs<(NUM_MSGS_TEST-1))
      {
        // Do next message
        num_msgs += 1;
      }
      else
      {
        // Done read messages, repeat from reset
        state = WAIT_RESET;
      }
    }
  }
 
  // Resets
  if(from_mem.ui_clk_sync_rst)
  {
    state = WAIT_RESET;
  }
   
  // Drive wires into memory controller
  WIRE_WRITE(xil_app_to_mig_t, xil_app_to_mig, to_mem)  
}
