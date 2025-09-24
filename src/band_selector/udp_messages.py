__author__ = 'J. B. Otterson'
__copyright__ = """
Copyright 2025, J. B. Otterson N1KDO.
Redistribution and use in source and binary forms, with or without modification, 
are permitted provided that the following conditions are met:
  1. Redistributions of source code must retain the above copyright notice, 
     this list of conditions and the following disclaimer.
  2. Redistributions in binary form must reproduce the above copyright notice, 
     this list of conditions and the following disclaimer in the documentation 
     and/or other materials provided with the distribution.
THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND 
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT,
INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, 
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE 
OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED
OF THE POSSIBILITY OF SUCH DAMAGE.
"""
__version__ = '0.0.1'

from ringbuf_queue import RingbufQueue
from utils import upython
import asyncio
if upython:
    import micro_logging as logging
else:
    import logging
import socket
from struct import calcsize, pack_into, unpack

'''
        payload = {'radio_1_antenna': antennas_selected[0],  # is int (0->8), could be uint8
                   'radio_2_antenna': antennas_selected[1],  # is int (0->8), could be uint8
                   'radio_names': config['radio_names'],     # 2x16 char limit from UI
                   'antenna_names': config['antenna_names'], # 8x20 char limit from UI
                   'antenna_bands': config['antenna_bands'], # 8x int, could be uint16
                   # 'hostname': config['hostname'],         # 64 char limit from UI
                   }
'''
# uint8 uint8 16s 16s 20s 20s 20s 20s 20s 20s 20s 20s hhhhhhhh64s
STATUS_BROADCAST_FMT = 'BB16s16s20s20s20s20s20s20s20s20shhhhhhhh64s'
STATUS_BROADCAST_SIZE = calcsize(STATUS_BROADCAST_FMT)
RADIO_1_ANTENNA_OFFSET = 0
RADIO_2_ANTENNA_OFFSET = 1
RADIO_NAMES_OFFSET = 2
RADIO_NAMES_SIZE = 2
ANTENNA_NAMES_OFFSET = 4
ANTENNA_NAMES_SIZE = 8
ANTENNA_BANDS_OFFSET = 12
ANTENNA_BANDS_SIZE = 8
SWITCH_NAME_OFFSET = 20


def calculate_broadcast_address(ip_address, netmask):
    # calculate the subnet's broadcast address using ip_address and netmask
    ip_int = sum([int(x) << 8 * i for i, x in enumerate(reversed(ip_address.split('.')))])
    mask_int = sum([int(x) << 8 * i for i, x in enumerate(reversed(netmask.split('.')))])
    mask_mask = mask_int ^ 0xffffffff
    bcast_int = ip_int | mask_mask
    # TODO make this into bytes, not str -- maybe
    bcast_addr = ".".join(map(str, [
        ((bcast_int >> 24) & 0xff),
        ((bcast_int >> 16) & 0xff),
        ((bcast_int >> 8) & 0xff),
        (bcast_int & 0xff),
    ]))
    return bcast_addr


class SendBroadcasts:
    """
    class to send UDP status datagrams
    """

    def __init__(self, target_ip, target_port, config: dict, antennas_selected:[]):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sockaddr = socket.getaddrinfo(target_ip, target_port)[0][-1]
        self.config = config
        self.antennas_selected = antennas_selected
        self.buf = bytearray(STATUS_BROADCAST_SIZE)
        logging.info(f'Broadcast address is {target_ip}:{target_port}', 'udp_messages:SendBroadcasts()')
        logging.info(f'Starting status broadcasts', 'udp_messages:SendBroadcasts()')
        self.run = True

    def send(self, payload):
        self.socket.sendto(payload, self.sockaddr)

    async def send_datagrams(self):
        radio_names = self.config['radio_names']
        antenna_names = self.config['antenna_names']
        antenna_bands = self.config['antenna_bands']
        antennas_selected = self.antennas_selected
        hostname = self.config['hostname']
        buf = self.buf
        sleep = asyncio.sleep
        while self.run:
            pack_into(STATUS_BROADCAST_FMT, buf, 0,
                  antennas_selected[0],
                      antennas_selected[1],
                      radio_names[0],
                      radio_names[1],
                      antenna_names[0],
                      antenna_names[1],
                      antenna_names[2],
                      antenna_names[3],
                      antenna_names[4],
                      antenna_names[5],
                      antenna_names[6],
                      antenna_names[7],
                      antenna_bands[0],
                      antenna_bands[1],
                      antenna_bands[2],
                      antenna_bands[3],
                      antenna_bands[4],
                      antenna_bands[5],
                      antenna_bands[6],
                      antenna_bands[7],
                      hostname)
            self.send(buf)
            await sleep(1.0)

    def stop(self):
        self.run = False


class ReceiveBroadcasts:
    """
    class that receives antenna control UDP messages from BandSelectors.
    None of this is implemented yet.
    """

    def __init__(self, receive_ip, receive_port, config:dict, message_queue: RingbufQueue, message_id: int):
        self.receive_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.receive_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.msgq = message_queue
        self.msgid = message_id
        self.buf = bytearray(STATUS_BROADCAST_SIZE)
        self.run = True
        try:
            sockaddr = socket.getaddrinfo(receive_ip, receive_port)[0][-1]
            self.receive_socket.bind(sockaddr)
            self.receive_socket.settimeout(0.001)
            logging.info(f'Broadcast address is {receive_ip}:{receive_port}', 'udp_messages:ReceiveBroadcasts.init')
            logging.info(f'Listening for status broadcasts', 'udp_messages:ReceiveBroadcasts.init')

        except Exception as exc:
            logging.exception('problem setting up socket', 'udp_messages:ReceiveBroadcasts.init', exc_info=exc)

    async def wait_for_datagram(self):
        while self.run:
            try:
                bytes_in = self.receive_socket.readinto(self.buf)
                logging.debug(f'udp_data "{self.buf}"', 'udp_messages:ReceiveBroadcasts:wait_for_datagram')
                stuff = unpack(STATUS_BROADCAST_FMT, self.buf)
                data = []
                for item in stuff:
                    if isinstance(item, bytes):
                        item = item.partition(b'\0')[0].decode()
                    data.append(item)
                logging.debug(f'message data "{data}"', 'udp_messages:ReceiveBroadcasts:wait_for_datagram')
                msg = (self.msgid, data)
                await self.msgq.put(msg)
            except OSError as exc:
                # this is a timeout exception, no data was received, this is not abnormal.
                pass
            except Exception as exc:
                logging.exception('problem receiving datagram',
                                  'udp_messages:ReceiveBroadcasts.:wait_for_datagram', exc_info=exc)
            await asyncio.sleep(0.1)
        while self.run:
            pass

    def stop(self):
        self.run = False
