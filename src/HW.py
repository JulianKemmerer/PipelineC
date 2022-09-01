#!/usr/bin/env python

import math
import os
import socket
import struct
import subprocess
import sys

# Source values for localhost
INTERFACE = "enx0050b6248f73"
SRC_MAC = bytes.fromhex("FEEDFACEBEEF")
SRC_IP = "1.2.3.4"
SRC_PORT = 1234

MEMCACHED_GET = 0
MEMCACHED_SET = 1


def send_eth(payload, dst, type=None, interface=INTERFACE):
    # 48-bit Ethernet addresses
    # print(len(SRC_MAC),SRC_MAC)
    assert len(SRC_MAC) == len(dst) == 6

    if type is None:
        l = len(payload) + 20
        type = struct.pack("<H", l)

    # 16-bit Ethernet type
    assert len(type) == 2  # 16-bit Ethernet type

    s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW)
    s.bind((interface, 0))
    return s.send(dst + SRC_MAC + type + payload)


def send_ip(
    payload, dst_ip_str, dst_mac, proto=254
):  # default protocol experimentation and testing
    # Form IP packet
    IP_VER = 4
    IP_IHL = 5
    IP_TOS = 0
    IP_TOL = 20 + len(payload)
    IP_IDT = 54331
    IP_FLG = 2  # 0x02 DF
    IP_FOS = 0
    IP_TTL = 64
    IP_PROTO = proto
    IP_CHECKSUM = 0  # FUCK IT FOR NOW?

    IP_IHL_VER = (IP_VER << 4) + IP_IHL

    src_ip = socket.inet_aton(SRC_IP)
    dst_ip = socket.inet_aton(dst_ip_str)

    IP_HEADER = struct.pack(
        "!BBHHHBBH4s4s",
        IP_IHL_VER,
        IP_TOS,
        IP_TOL,
        IP_IDT,
        IP_FOS,
        IP_TTL,
        IP_PROTO,
        IP_CHECKSUM,
        src_ip,
        dst_ip,
    )

    IP_PACKET = IP_HEADER + payload

    ethertype = "\x08\x00"  # IP

    # Send in ETH frame
    return send_eth(IP_PACKET, dst_mac, ethertype)


def send_udp(payload, dst_port, dst_ip, dst_mac):
    # Form UDP packet
    length = len(payload) + 8
    checksum = 0
    UDP_HEADER = struct.pack("!HHHH", SRC_PORT, dst_port, length, checksum)
    UDP_PACKET = UDP_HEADER + payload
    proto = 17  # UDP
    # Send in IP packet
    return send_ip(UDP_PACKET, dst_ip, dst_mac, proto)


def send_memcached_request(key, value, opcode):
    """
    Request header
       Byte/     0       |       1       |       2       |       3       |
          /              |               |               |               |
         |0 1 2 3 4 5 6 7|0 1 2 3 4 5 6 7|0 1 2 3 4 5 6 7|0 1 2 3 4 5 6 7|
         +---------------+---------------+---------------+---------------+
        0| Magic         | Opcode        | Key length                    |
         +---------------+---------------+---------------+---------------+
        4| Extras length | Data type     | vbucket id                    |
         +---------------+---------------+---------------+---------------+
        8| Total body length                                             |
         +---------------+---------------+---------------+---------------+
       12| Opaque                                                        |
         +---------------+---------------+---------------+---------------+
       16| CAS                                                           |
         |                                                               |
         +---------------+---------------+---------------+---------------+
         Total 24 bytes
       +---------------+---------------+---------------+---------------+
       24/ COMMAND-SPECIFIC EXTRAS (as needed)                           /
        +/  (note length in the extras length header field)              /
         +---------------+---------------+---------------+---------------+
        m/ Key (as needed)                                               /
        +/  (note length in key length header field)                     /
         +---------------+---------------+---------------+---------------+
        n/ Value (as needed)                                             /
        +/  (note length is total body length header field, minus        /
        +/   sum of the extras and key length body fields)               /
         +---------------+---------------+---------------+---------------+
    """
    magic = 0x80
    keylen = len(key)
    if value is None:
        value = ""
    valuelen = len(value)
    if opcode == MEMCACHED_GET:
        extraslen = 0
        extras_bytes = ""
    elif opcode == MEMCACHED_SET:
        extras_flags = 0xDEADBEEF
        extras_expir = 0
        extraslen = 8
        extras_bytes = struct.pack("!II", extras_flags, extras_expir)
    else:
        print(0 / 0)
    datatype = 0
    vbucket = 0
    totalbodylen = extraslen + keylen + valuelen
    opaque = 0
    cas = 0

    # Pack up the header
    # B unsigned char 1
    # H unsigned short 2
    # I unsigned int 4
    # Q unsigned long long 8
    header_bytes = struct.pack(
        "!BBHBBHIIQ",
        magic,
        opcode,
        keylen,
        extraslen,
        datatype,
        vbucket,
        totalbodylen,
        opaque,
        cas,
    )

    # Pack up extras key and value
    key_bytes = struct.pack("!" + str(len(key)) + "s", key)
    value_bytes = struct.pack("!" + str(valuelen) + "s", value)

    # Form packet
    packet_bytes = header_bytes + extras_bytes + key_bytes + value_bytes

    # Send as udp packet
    dst_port = 11211
    dst_ip = "5.6.7.8"
    dst_mac = "\xFE\xED\xFA\xCE\xBE\xEF"
    send_udp(packet_bytes, dst_port, dst_ip, dst_mac)


def send_memcached_get(key):
    opcode = MEMCACHED_GET
    send_memcached_request(key, None, opcode)


def send_memcached_set(key, value):
    opcode = MEMCACHED_SET
    send_memcached_request(key, value, opcode)


TWO_NUMS = struct.pack("!QQ", 123, 456)
# TWO_NUMS = struct.pack("!ff", 1.23, 4.56)
# LONG_STR = "Hello this is a test of a longer packet since minimum frames sizes add padding it seems?" #struct.pack("!s",
# print "LONG_STR",LONG_STR
# send_udp(TWO_NUMS, 5678, "5.6.7.8", "\xFE\xED\xFA\xCE\xBE\xEF")
print("Sending from:", INTERFACE)
# send_memcached_set("hello", "world")
# import time
# time.sleep(1)
# send_memcached_get("hello")
dst_mac = bytes.fromhex("012345678901")
send_eth(TWO_NUMS, dst_mac)
