#!/usr/bin/env python3

# Import essential libraries
import os
import sys
import requests
import cv2
import numpy as np
import imutils
from imutils import adjust_brightness_contrast

# Package as a struct that C code can decode
from ctypes import *


def convert_struct_to_bytes(st):
    buffer = create_string_buffer(sizeof(st))
    memmove(buffer, addressof(st), sizeof(st))
    return buffer.raw


# TODO Code gen python stuff based on C struct defs?
N_PIXELS_PER_UPDATE = 16


class pixels_update_t(Structure):
    _fields_ = [
        ("pixels", c_uint8 * N_PIXELS_PER_UPDATE),
        ("addr", c_uint16),
        ("pad19", c_uint8),
        ("pad20", c_uint8),
    ]


# Small resolution from setup on IP camera phone
url = "http://192.168.86.85:8080/shot.jpg"
x_res = 176
y_res = 144

# Write binary data to standard out, C program will be listening
with os.fdopen(sys.stdout.fileno(), "wb", closefd=False) as stdout:
    # While loop to continuously fetching data from the Url
    while True:
        # Get image
        img_resp = requests.get(url)
        img_arr = np.array(bytearray(img_resp.content), dtype=np.uint8)
        img = cv2.imdecode(img_arr, -1)
        # Crop a square
        sq_img = img[0:y_res, 0:y_res]
        # Grayscale
        gray_img = cv2.cvtColor(sq_img, cv2.COLOR_BGR2GRAY)
        # Resized for mnist
        mnist_img = imutils.resize(gray_img, width=28, height=28)
        # Increase contrast/filter
        # adjusted_mnist_img = adjust_brightness_contrast(mnist_img, contrast=50.0, brightness=0.0)
        # mnist_img_filtered = cv2.inRange(mnist_img, 100, 255)
        ret, mnist_img_filtered = cv2.threshold(mnist_img, 128, 255, cv2.THRESH_TOZERO)
        # Resize for display
        large_mnist = imutils.resize(mnist_img_filtered, width=1000, height=1000)
        cv2.imshow("mnist", large_mnist)

        # Send the bytes of pixel updates over std out
        # Make groups of N and write them
        addr = 0
        group_of_n = []
        for i in range(0, 28):
            for j in range(0, 28):
                group_of_n.append(mnist_img_filtered[i][j])
                if len(group_of_n) == N_PIXELS_PER_UPDATE:
                    update = pixels_update_t()
                    update.addr = addr
                    for n in range(0, N_PIXELS_PER_UPDATE):
                        update.pixels[n] = group_of_n[n]
                    group_of_n = []
                    addr += 1
                    stdout.write(convert_struct_to_bytes(update))
        stdout.flush()

        # Press Esc key to exit
        if cv2.waitKey(1) == 27:
            break

    cv2.destroyAllWindows()
