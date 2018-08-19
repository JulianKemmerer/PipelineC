#!/usr/bin/env python

import sys
import os
import subprocess
import math
import struct
import socket

INTERFACE = "enx0050b6248f73"
SRC_MAC = "\xFE\xED\xFA\xCE\xBE\xEF"
SRC_IP = "1.2.3.4"
SRC_PORT = 1234

def send_eth(payload, dst, type=None, interface=INTERFACE):
	# 48-bit Ethernet addresses
	assert(len(SRC_MAC) == len(dst) == 6)

	if type is None:
		l = len(payload)+20
		type =struct.pack("<H", l)

	# 16-bit Ethernet type
	assert(len(type) == 2) # 16-bit Ethernet type

	s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW)
	s.bind((interface, 0))
	return s.send(dst + SRC_MAC + type + payload)
  

def send_ip(payload, dst_ip_str, dst_mac, proto=254): # default protocol experimentation and testing
	# Form IP packet
	IP_VER = 4
	IP_IHL = 5
	IP_TOS = 0
	IP_TOL = 20 + len(payload)
	IP_IDT = 54331
	IP_FLG = 2 # 0x02 DF
	IP_FOS = 0
	IP_TTL = 64
	IP_PROTO = proto 
	IP_CHECKSUM = 0 # FUCK IT FOR NOW?

	IP_IHL_VER = (IP_VER << 4) + IP_IHL

	src_ip = socket.inet_aton(SRC_IP)
	dst_ip = socket.inet_aton(dst_ip_str)

	IP_HEADER = struct.pack("!BBHHHBBH4s4s", IP_IHL_VER, IP_TOS, IP_TOL, IP_IDT, IP_FOS, IP_TTL, IP_PROTO, IP_CHECKSUM, src_ip, dst_ip)
	
	IP_PACKET = IP_HEADER + payload
	
	ethertype = "\x08\x00" # IP
	
	# Send in ETH frame
	return send_eth(IP_PACKET,dst_mac, ethertype)


def send_udp(payload, dst_port, dst_ip, dst_mac):
	# Form UDP packet
	length = len(payload) + 8
	checksum = 0
	UDP_HEADER = struct.pack("!HHHH", SRC_PORT, dst_port, length, checksum)
	UDP_PACKET = UDP_HEADER + payload
	proto=17 # UDP
	# Send in IP packet
	return send_ip(UDP_PACKET, dst_ip, dst_mac, proto)

	
if __name__ == "__main__":
	#TWO_NUMS = struct.pack("!QQ", 123, 456)
	TWO_NUMS = struct.pack("!ff", 1.23, 4.56)
	#LONG_STR = "Hello this is a test of a longer packet since minimum frames sizes add padding it seems?" #struct.pack("!s", 
	#print "LONG_STR",LONG_STR
	print( ("Sent %d-byte Ethernet packet on " + INTERFACE) %
	      send_udp(TWO_NUMS, 5678, "5.6.7.8", "\xFE\xED\xFA\xCE\xBE\xEF") )
		
