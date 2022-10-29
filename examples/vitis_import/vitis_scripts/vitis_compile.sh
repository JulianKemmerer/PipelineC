#!/bin/bash
v++ -g \
    --compile \
    --platform $2 \
    --input_files sources/maxi_to_stream.cpp \
    --config sources/vitis_hls.cfg \
    --kernel maxi_to_stream \
    --output xo/maxi_to_stream.xo \
    --target $1
v++ -g \
    --compile \
    --platform $2 \
    --input_files sources/stream_to_maxi.cpp \
    --config sources/vitis_hls.cfg \
    --kernel stream_to_maxi \
    --output xo/stream_to_maxi.xo \
    --target $1
