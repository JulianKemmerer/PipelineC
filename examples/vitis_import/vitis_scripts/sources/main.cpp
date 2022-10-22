/**
* Copyright (C) 2019-2021 Xilinx, Inc
*
* Licensed under the Apache License, Version 2.0 (the "License"). You may
* not use this file except in compliance with the License. A copy of the
* License is located at
*
*     http://www.apache.org/licenses/LICENSE-2.0
*
* Unless required by applicable law or agreed to in writing, software
* distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
* WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
* License for the specific language governing permissions and limitations
* under the License.
*/

// Original source file can be found in Xilinx Github repository
// https://github.com/Xilinx/Vitis_Accel_Examples/blob/master/hello_world/src/host.cpp
// This file is modified!

#include "../includes/xcl2.hpp"
#include <algorithm>
#include <vector>
#define DATA_SIZE 64

int main(int argc, char** argv) {
    if (argc != 2) {
        std::cout << "Usage: " << argv[0] << " <XCLBIN File>" << std::endl;
        return EXIT_FAILURE;
    }

    std::string binaryFile = argv[1];
    size_t vector_size_bytes = sizeof(int) * DATA_SIZE;
    cl_int err;
    cl::Context context;
    cl::Kernel krnl_maxi_to_stream;
    cl::Kernel krnl_stream_to_maxi;
    cl::CommandQueue q;

    std::vector<int, aligned_allocator<int> > source_in1(DATA_SIZE);
    std::vector<int, aligned_allocator<int> > source_hw_results(DATA_SIZE);
    std::vector<int, aligned_allocator<int> > source_sw_results(DATA_SIZE);

    // Create the test data
    std::generate(source_in1.begin(), source_in1.end(), std::rand);
    for (int i = 0; i < DATA_SIZE; i++) {
        source_sw_results[i] = source_in1[i] + 1;
        source_hw_results[i] = 0;
    }

    auto devices = xcl::get_xil_devices();
    auto fileBuf = xcl::read_binary_file(binaryFile);
    cl::Program::Binaries bins{{fileBuf.data(), fileBuf.size()}};
    bool valid_device = false;
    for (unsigned int i = 0; i < devices.size(); i++) {
        auto device = devices[i];
        // Creating Context and Command Queue for selected Device
        OCL_CHECK(err, context = cl::Context(device, nullptr, nullptr, nullptr, &err));
        OCL_CHECK(err, q = cl::CommandQueue(context, device, CL_QUEUE_PROFILING_ENABLE | CL_QUEUE_OUT_OF_ORDER_EXEC_MODE_ENABLE, &err));
        std::cout << "Trying to program device[" << i << "]: " << device.getInfo<CL_DEVICE_NAME>() << std::endl;
        cl::Program program(context, {device}, bins, nullptr, &err);
        if (err != CL_SUCCESS) {
            std::cout << "Failed to program device[" << i << "] with xclbin file!\n";
        } else {
            std::cout << "Device[" << i << "]: program successful!\n";
            OCL_CHECK(err, krnl_maxi_to_stream = cl::Kernel(program, "maxi_to_stream", &err));
            OCL_CHECK(err, krnl_stream_to_maxi = cl::Kernel(program, "stream_to_maxi", &err));
            valid_device = true;
            break; // we break because we found a valid device
        }
    }
    if (!valid_device) {
        std::cout << "Failed to program any device found, exit!\n";
        exit(EXIT_FAILURE);
    }

    OCL_CHECK(err, cl::Buffer buffer_in(context, CL_MEM_USE_HOST_PTR | CL_MEM_READ_ONLY, vector_size_bytes,
                                         source_in1.data(), &err));
    OCL_CHECK(err, cl::Buffer buffer_output(context, CL_MEM_USE_HOST_PTR | CL_MEM_WRITE_ONLY, vector_size_bytes,
                                            source_hw_results.data(), &err));

    unsigned int size = DATA_SIZE;
    OCL_CHECK(err, err = krnl_maxi_to_stream.setArg(0, buffer_in));
    OCL_CHECK(err, err = krnl_maxi_to_stream.setArg(2, size));
    OCL_CHECK(err, err = krnl_stream_to_maxi.setArg(1, buffer_output));
    OCL_CHECK(err, err = krnl_stream_to_maxi.setArg(2, size));
    OCL_CHECK(err, err = q.enqueueMigrateMemObjects({buffer_in}, 0 /* 0 means from host*/));
    OCL_CHECK(err, err = q.enqueueTask(krnl_maxi_to_stream));
    OCL_CHECK(err, err = q.enqueueTask(krnl_stream_to_maxi));
    q.finish();
    OCL_CHECK(err, err = q.enqueueMigrateMemObjects({buffer_output}, CL_MIGRATE_MEM_OBJECT_HOST));
    q.finish();

    bool match = true;
    for (int i = 0; i < DATA_SIZE; i++) {
        if (source_hw_results[i] != source_sw_results[i]) {
            std::cout << "Error: Result mismatch" << std::endl;
            std::cout << "i = " << i << " CPU result = " << source_sw_results[i]
                      << " Device result = " << source_hw_results[i] << std::endl;
            match = false;
            break;
        }
    }

    std::cout << "TEST " << (match ? "PASSED" : "FAILED") << std::endl;
    return (match ? EXIT_SUCCESS : EXIT_FAILURE);
}
