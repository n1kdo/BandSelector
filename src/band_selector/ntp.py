#
# ntp.py -- set pico time from NTP
#
# Copyright 2024, 2025, 2026, J. B. Otterson N1KDO.
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
#
__author__ = 'J. B. Otterson'
__copyright__ = 'Copyright 2024, 2025, 2026 J. B. Otterson N1KDO.'
__version__ = '0.1.2'  # 2026-09-13

#
# All network I/O in this module is async-safe: sockets are non-blocking and the
# code yields to the asyncio event loop while waiting, so a slow or blackholed
# DNS/NTP server can never starve the watchdog feeder task.  (MicroPython's
# asyncio has no UDP/DatagramProtocol support, so we poll a non-blocking socket
# with short loop yields instead.)
#
# Host names are resolved with a minimal RFC 1035 A-record client that queries
# the port-53 DNS server(s) supplied by the caller -- no synchronous
# socket.getaddrinfo() anywhere.
#

import asyncio
import random
import socket
import struct
import sys
import time

_IS_MICROPYTHON = sys.implementation.name == 'micropython'

if _IS_MICROPYTHON:
    from machine import RTC
    _rtc = RTC()
    from time import ticks_ms, ticks_diff
    import micro_logging as logging
    from asyncio import TimeoutError  # micropython has no builtin TimeoutError
else:
    _rtc = None
    def const(i):
        return i
    def ticks_ms():
        return int(time.monotonic() * 1000)
    def ticks_diff(a, b):
        return a - b
    import micro_logging as logging  # stdlib logging.exception() has a different signature
    from asyncio.exceptions import TimeoutError  # same class as the builtin on 3.11+

_UNIX_EPOCH = const(2208988800)  # 1970-01-01 00:00:00
_NTP_PORT = const(123)
_DNS_PORT = const(53)
_BUF_SIZE = const(1024)
_NTP_MSG = b'\x1b' + b'\0' * 47
_NTP_TIMEOUT_MS = const(2000)   # per NTP server; well inside the watchdog budget
_DNS_TIMEOUT_MS = const(2000)   # per DNS server
_DNS_POLL_MS = const(50)        # non-blocking recv poll interval
_STRUCT_FORMAT = '!12I'


# ---------------------------------------------------------------------------
# Minimal RFC 1035 DNS client (A records only).
# ---------------------------------------------------------------------------

def _is_ipv4(s):
    parts = s.split('.')
    if len(parts) != 4:
        return False
    for p in parts:
        if not p.isdigit() or int(p) > 255:
            return False
    return True


def _encode_dns_name(name):
    out = bytearray()
    for label in name.split('.'):
        lb = label.encode()
        if len(lb) > 63:
            raise ValueError('DNS label too long')
        out.append(len(lb))
        out.extend(lb)
    out.append(0)
    return bytes(out)


def _build_a_query(txid, host):
    # header: ID, flags=RD, QD=1, AN=NS=AR=0; question: name, TYPE=A(1), CLASS=IN(1)
    return (struct.pack('!HHHHHH', txid, 0x0100, 1, 0, 0, 0)
            + _encode_dns_name(host)
            + struct.pack('!HH', 1, 1))


def _read_dns_name(data, off):
    """Walk a (possibly compressed) DNS name.  Returns (name_str, new_offset)."""
    labels = []
    end = None
    while True:
        if off >= len(data):
            raise ValueError('truncated DNS name')
        l = data[off]
        if l & 0xC0:
            if off + 1 >= len(data):
                raise ValueError('truncated DNS name pointer')
            if end is None:
                # a pointer means the name "ends" after this 2-byte pointer
                end = off + 2
            off = ((l & 0x3F) << 8) | data[off + 1]
        elif l == 0:
            break
        else:
            if l > 63 or off + 1 + l > len(data):
                raise ValueError('bad DNS label')
            labels.append(bytes(data[off + 1:off + 1 + l]))
            off += 1 + l
    return b'.'.join(labels).decode(), (end if end is not None else off + 1)


def _parse_a_response(txid, data):
    """Return the first IPv4 A record as a dotted-quad string.

    Raises LookupError if the response contains no A record, ValueError if the
    response is malformed or does not match txid.
    """
    if len(data) < 12:
        raise ValueError('DNS response too short')
    rid, flags, qdcount, ancount = struct.unpack('!4H', data[:8])
    if rid != txid:
        raise ValueError('DNS transaction id mismatch')
    if not (flags & 0x8000):
        raise ValueError('DNS response QR bit not set')
    rcode = flags & 0x0F
    off = 12
    for _ in range(qdcount):
        _, off = _read_dns_name(data, off)
        off += 4  # qtype + qclass
    for _ in range(ancount):
        _, off = _read_dns_name(data, off)
        if off + 10 > len(data):
            raise ValueError('truncated DNS record')
        rtype, rclass = struct.unpack('!HH', data[off:off + 4])
        off += 8  # type, class, ttl
        rdlen = struct.unpack('!H', data[off:off + 2])[0]
        off += 2
        if rtype == 1 and rclass == 1 and rdlen == 4:
            # MicroPython's socket has no inet_ntoa; format the 4 octets directly.
            ip = data[off:off + 4]
            return '%d.%d.%d.%d' % (ip[0], ip[1], ip[2], ip[3])
        off += rdlen
    raise LookupError('no A record in DNS response (rcode=%d)' % rcode)


async def _recvfrom_async(sock, timeout_ms):
    """Receive one datagram from a non-blocking socket, yielding to the event
    loop until data arrives or timeout_ms elapses.  Returns the datagram bytes.
    Raises TimeoutError on expiry."""
    deadline = ticks_ms() + timeout_ms
    while True:
        try:
            return sock.recvfrom(_BUF_SIZE)[0]
        except OSError:
            # EAGAIN/EWOULDBLOCK: no datagram yet.  Other OSErrors are treated
            # the same and will run out the clock; bounded by the deadline.
            if ticks_diff(deadline, ticks_ms()) <= 0:
                raise TimeoutError('UDP recv timed out')
            await asyncio.sleep(_DNS_POLL_MS / 1000)


async def dns_a_query(host, dns_servers, timeout_ms=_DNS_TIMEOUT_MS):
    """Resolve host to an IPv4 dotted-quad string with raw port-53 DNS queries.

    dns_servers: a dotted-quad string, or an iterable of dotted-quad strings;
    servers are tried in order until one answers.  Never blocks the event loop.
    Raises LookupError/ValueError/OSError/TimeoutError if every server fails.
    """
    if isinstance(dns_servers, str):
        dns_servers = (dns_servers,)
    txid = random.getrandbits(16)
    query = _build_a_query(txid, host)
    last_exc = None
    for server in dns_servers:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(0)  # non-blocking; we poll with loop yields
            sock.sendto(query, (server, _DNS_PORT))
            data = await _recvfrom_async(sock, timeout_ms)
            return _parse_a_response(txid, data)
        except (TimeoutError, ValueError, LookupError, OSError) as ex:
            last_exc = ex
            logging.debug('DNS query to %s failed: %s' % (server, ex), 'ntp:dns_a_query')
        finally:
            sock.close()
    raise last_exc


# ---------------------------------------------------------------------------
# NTP (RFC 4330, mode-3 client).
# ---------------------------------------------------------------------------

async def get_ntp_time(host='pool.ntp.org', dns_servers=None):
    """Set the RTC from an NTP server and return the time.gmtime() tuple.

    host may be a host name (resolved via dns_a_query using dns_servers) or a
    dotted-quad address.  Returns None on any failure.  Async-safe: yields to
    the event loop for all network waits.
    """
    sock = None
    try:
        if _is_ipv4(host):
            ntp_address = host
        else:
            if not dns_servers:
                raise LookupError('no DNS servers available to resolve %s' % host)
            ntp_address = await dns_a_query(host, dns_servers)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0)  # non-blocking; we poll with loop yields
        sock.sendto(_NTP_MSG, (ntp_address, _NTP_PORT))
        msg = await _recvfrom_async(sock, _NTP_TIMEOUT_MS)

        ntp_size = struct.calcsize(_STRUCT_FORMAT)
        if len(msg) < ntp_size:
            raise ValueError('short NTP packet')
        # unpack the fixed 48-byte header only: servers may append the
        # optional auto-key extension (RFC 4330), and struct.unpack()
        # requires an exact-size buffer on both runtimes.
        t = struct.unpack(_STRUCT_FORMAT, msg[:ntp_size])[10] - _UNIX_EPOCH
        tt = time.gmtime(t)
        if _IS_MICROPYTHON:
            # set the RTC
            try:
                _rtc.datetime((tt[0], tt[1], tt[2], tt[6], tt[3], tt[4], tt[5], 0))
            except OSError as e:
                logging.exception('error setting time', 'ntp:get_ntp_time', e)
        return tt
    except Exception as ex:
        logging.exception('error getting ntp time', 'ntp:get_ntp_time', ex)
        return None
    finally:
        if sock is not None:
            sock.close()


def main():
    # standalone test:  python ntp.py [dns_server ...]
    import sys as _sys
    servers = tuple(_sys.argv[1:]) or ('1.1.1.1', '8.8.8.8')
    tt = asyncio.run(get_ntp_time(dns_servers=servers))
    print('ntptime: ', tt)
    if tt is not None:
        dt = f'{tt[0]:04d}-{tt[1]:02d}-{tt[2]:02d}T{tt[3]:02d}:{tt[4]:02d}:{tt[5]:02d}+00:00'
        print(dt)


if __name__ == '__main__':
    main()
