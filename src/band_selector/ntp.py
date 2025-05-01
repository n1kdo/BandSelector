import socket
import struct
import sys
import time

_IS_MICROPYTHON = sys.implementation.name == 'micropython'

if _IS_MICROPYTHON:
    from machine import RTC
    _rtc = RTC()
else:
    _rtc = None
    def const(i):
        return i

_UNIX_EPOCH = const(2208988800)  # 1970-01-01 00:00:00
_NTP_PORT = const(123)
_BUF_SIZE = const(1024)
_NTP_MSG = b'\x1b' + b'\0' * 47
_SOCKET_TIMEOUT = const(5)
_STRUCT_FORMAT = '!12I'

def get_ntp_time(host='pool.ntp.org'):
    sock = None
    try:
        address = socket.getaddrinfo(host, _NTP_PORT)[0][-1]
        # connect to server
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(_SOCKET_TIMEOUT)
        sock.sendto(_NTP_MSG, address)
        msg = sock.recvfrom(_BUF_SIZE)[0]
        sock.close()

        t = struct.unpack(_STRUCT_FORMAT, msg)[10] - _UNIX_EPOCH
        tt = time.gmtime(t)
        if _IS_MICROPYTHON:
            # set the RTC
            try:
                _rtc.datetime((tt[0], tt[1], tt[2], tt[6], tt[3], tt[4], tt[5], 0))
            except OSError as e:
                print(e)
        return tt
    except OSError as ose:
        print(ose)
        return None
    finally:
        if sock:
            sock.close()


def main():
    ntp_time = get_ntp_time()
    print('ntptime: ', ntp_time)
    tt = time.gmtime()
    print('gmtime:  ', tt)
    dt = f'{tt[0]:04d}-{tt[1]:02d}-{tt[2]:02d}T{tt[3]:02d}:{tt[4]:02d}:{tt[5]:02d}+00:00'
    print(dt)


if __name__ == '__main__':
    main()
