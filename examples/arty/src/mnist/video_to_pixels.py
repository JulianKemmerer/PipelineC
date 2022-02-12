#!/usr/bin/env python3

# Import essential libraries
import os
import sys
import requests
import cv2
import numpy as np
import imutils

# Package as a struct that C code can decode
from ctypes import *
def convert_struct_to_bytes(st):
    buffer = create_string_buffer(sizeof(st))
    memmove(buffer, addressof(st), sizeof(st))
    return buffer.raw
# TODO Code gen python stuff based on C struct defs?
'''
#define N_PIXELS_PER_UPDATE 1
#define pixel_t uint8_t
typedef struct pixels_update_t
{
    pixel_t pixels[N_PIXELS_PER_UPDATE];
    uint16_t addr;
    uint8_t pad0; // temp need to be >= 4 bytes
}pixels_update_t;
'''
class pixels_update_t(Structure):
    _fields_ = [('pixels', c_uint8 * 1),
                ('addr', c_uint16),
                ('pad0', c_uint8)]


# Small resolution from IP camera phone
url = "http://192.168.86.85:8080/shot.jpg"
x_res = 176
y_res = 144
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
        # Resized for display
        large_mnist = imutils.resize(mnist_img, width=1000, height=1000)
        cv2.imshow("mnist", large_mnist)

        # Send the bytes of pixel updates over std out
        update = pixels_update_t()
        for i in range(0, 28):
            for j in range(0, 28):
                update.pixels[0] = mnist_img[i][j]
                update.addr = i*28 + j
                stdout.write(convert_struct_to_bytes(update))   
        stdout.flush()

        # Press Esc key to exit
        if cv2.waitKey(1) == 27:
            break
    
    cv2.destroyAllWindows()