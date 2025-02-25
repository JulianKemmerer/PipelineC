
// Software specific helper functions to convert ethernet reads/write bytes to/from 'work' inputs/outputs

void input_write(work_inputs_t* input)
{
 // Copy into buffer
 uint8_t buffer[work_inputs_t_SIZE];
 work_inputs_t_to_bytes(input, buffer);
 // Send buffer
 eth_write(buffer, work_inputs_t_SIZE);  
}
void output_read(work_outputs_t* output)
{
  // Read buffer
  uint8_t buffer[work_outputs_t_SIZE];
  size_t rd_size = work_outputs_t_SIZE;
  eth_read(buffer, &rd_size);
  if(rd_size != work_outputs_t_SIZE)
  {
    printf("Did not receive enough bytes! Expected %d, got %ld\n",work_outputs_t_SIZE,rd_size);
  }
  // Copy from buffer
  bytes_to_work_outputs_t(buffer,output);
}

