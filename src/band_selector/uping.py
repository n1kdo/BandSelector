# ping for python and micropython
#
# adapted from: https://gist.github.com/shawwwn/91cc8979e33e82af6d99ec34c38195fb
# µPing (MicroPing) for MicroPython
# copyright (c) 2018 Shawwwn <shawwwn1@gmail.com>
# License: MIT
#
# That was apparently derived from https://github.com/olavmrk/python-ping/blob/master/ping.py
# which has a MIT license: Copyright (c) 2016 Olav Morken


__author__ = 'J. B. Otterson'
__copyright__ = 'Copyright 2025 J. B. Otterson N1KDO.'
__version__ = '0.1.0'

#
# Copyright 2025, J. B. Otterson N1KDO.
#
# Redistribution and use in source and binary forms, with or without modification,
# are permitted provided that the following conditions are met:
#
#  1. Redistributions of source code must retain the above copyright notice,
#     this list of conditions and the following disclaimer.
#  2. Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions and the following disclaimer in the documentation
#     and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
# IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT,
# INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE
# OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED
# OF THE POSSIBILITY OF SUCH DAMAGE.


from utils import upython

if not upython:
    import argparse
    import logging
else:
    import micro_logging as logging
import random
import select
import socket
import struct
import sys
import time


def time_us() -> int:
    """
    Get the current time in microseconds, but make it fit into an unsigned 32-bit int.
    This is useful for somewhat imprecise time measurements, such as ping.
    :return: an integer that will fit into an unsigned 32-bit int.
    """
    if upython:
        return time.ticks_us()
    else:
        return int(time.monotonic_ns() / 1000) % 4000000000


def make_ping_packet_bytes(ident=0, seq=0, ts_usec=0, payload=b'') -> bytes:
    cod = 8 # code uint8
    typ = 0 # type uint8
    checksum = 0  # checksum uint16
    ident = ident & 0xffff # ident uint16
    seq = seq & 0xffff # sequence int16
    # first assemble the packet without checksum
    # the size of the struct is 16 bytes. 1+1+2+2+2+4+4 = 16
    data = struct.pack('>BBHHhLL', cod, typ, checksum, ident, seq, ts_usec, 0) + payload
    # now calculate checksum
    if len(data) & 0x1: # odd number of bytes
        data += b'\0'  # pad to even number of bytes
    checksum = 0
    for pos in range(0, len(data), 2):
        b1 = data[pos]
        b2 = data[pos + 1]
        checksum += (b1 << 8) + b2
    while checksum >= 0x10000:
        checksum = (checksum & 0xffff) + (checksum >> 16)
    checksum = ~checksum & 0xffff
    # now create the actual packet with the checksum
    data = struct.pack('>BBHHhLL', cod, typ, checksum, ident, seq, ts_usec, 0) + payload
    return data


def decode_ping_response(data) -> tuple[int, int, int, int, int, int, bytes]:
    if len(data) < 16:
        raise ValueError('ICMP Echo packet must be at least 16 bytes')

    # 20 bytes of padding, then uint8, uint8, uint16, uint16, int16, uint32
    stuff = struct.unpack('>xxxxxxxxxxxxxxxxxxxxBBHHhL', data[0:32])
    typ = stuff[0]
    if typ not in (0, 8):
        raise ValueError('Not a ICMP Echo message (type={type})'.format(type=typ))
    code = stuff[1]
    checksum = stuff[2]
    ident = stuff[3]
    seq = stuff[4]
    ts = stuff[5]
    payload = data[32:]
    # print(f'type: {typ}, code: {code}, checksum: {checksum}, ident: {ident:x}, seq: {seq}, ts: {ts}')
    return typ, code, checksum, ident, seq, ts, payload


def ping(host, count=4, timeout=5000, interval=10, size=16) -> tuple[int, int]:
    assert size >= 0, "pkt size too small"
    payload = b'Q' * size

    # init socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, 1)
    sock.setblocking(0)
    sock.settimeout(timeout/1000)
    addr = socket.getaddrinfo(host, 1)[0][-1][0] # ip address
    sock.connect((addr, 1))
    logging.debug(f'PING {host} ({addr}): {len(payload)} data bytes')

    seqs = list(range(1, count+1)) # [1,2,...,count]
    ident = random.getrandbits(16)
    seq = 1
    t = 0
    n_trans = 0
    n_recv = 0
    finish = False
    while t < timeout:
        if t==interval and seq<=count:
            ts_usec = time_us()
            byts = make_ping_packet_bytes(ident, seq, ts_usec, payload)
            if sock.send(byts) == len(byts):
                n_trans += 1
                t = 0 # reset timeout
            else:
                seqs.remove(seq)
            seq += 1
        # recv packet
        while 1:
            socks, _, _ = select.select([sock], [], [], 0)
            if socks:
                resp = socks[0].recv(4096)
                r_typ, cod, cksum, r_ident, r_seq, ts, r_payload = decode_ping_response(resp)
                if r_typ==0 and r_ident==ident and (r_seq in seqs): # 0: ICMP_ECHO_REPLY
                    t_elapsed = (time_us() - ts) / 1000.0
                    ttl = 0
                    n_recv += 1
                    if logging.should_log(logging.DEBUG):
                        logging.debug(f'{len(resp)} bytes from {addr}: icmp_seq={r_seq}, ttl={ttl}, time={t_elapsed} ms')
                    seqs.remove(r_seq)
                    if len(seqs) == 0:
                        finish = True
                        break
                else:
                    if r_seq not in seqs:
                        logging.warning(f'{r_seq} not in {seqs}')
            else:
                break
        if finish:
            break

        if upython:
            time.sleep_ms(1)
        else:
            time.sleep(0.001)
        t += 1

    sock.close()
    if logging.should_log(logging.DEBUG):
        logging.debug(f'{n_trans} packets transmitted, {n_recv} packets received.')
    return n_trans, n_recv


if not upython:
    def main():
        parser = argparse.ArgumentParser(description='Simple Python ping script')
        parser.add_argument('target', type=str, help='Ping target')
        parser.add_argument('--count', type=int, help='Ping count times', default=4)
        parser.add_argument('--debug', action='store_true', help='show logging informational output')
        parser.add_argument('--info', action='store_true', help='show informational diagnostic output')
        args = parser.parse_args()

        log_format = '%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s'
        log_date_format = '%Y-%m-%d %H:%M:%S'
        if args.debug:
            logging.basicConfig(format=log_format, datefmt=log_date_format, level=logging.DEBUG, stream=sys.stderr)
        elif args.info:
            logging.basicConfig(format=log_format, datefmt=log_date_format, level=logging.INFO, stream=sys.stderr)
        else:
            logging.basicConfig(format=log_format, datefmt=log_date_format, level=logging.WARNING, stream=sys.stderr)
        logging.Formatter.converter = time.gmtime

        ping(args.target, count=args.count, size=0)

    if __name__ == '__main__':
        main()
