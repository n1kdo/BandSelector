#
# main.py -- this is the web server for the Raspberry Pi Pico W Band Selector controller.
#

__author__ = 'J. B. Otterson'
__copyright__ = 'Copyright 2022, 2024 J. B. Otterson N1KDO.'
__version__ = '0.0.1'

#
# Copyright 2022, 2024 J. B. Otterson N1KDO.
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

import json

from alcd import LCD
from button import Button
from fourbits import FourBits
from http_server import (HttpServer,
                         api_rename_file_callback,
                         api_remove_file_callback,
                         api_upload_file_callback,
                         api_get_files_callback)
from morse_code import MorseCode
from picow_network import PicowNetwork
from ringbuf_queue import RingbufQueue
from utils import milliseconds, upython, safe_int
import micro_logging as logging

if upython:
    import machine
    import uasyncio as asyncio
else:
    import asyncio
    from not_machine import machine

BANDS = ['None', '160M', '80M', '60M', '40M', '30M', '20M', '17M', '15M', '12M', '10M', '6M', '2M', '70cm']
# port_bands is a BITMASK, 16 bits wide.
BAND_160M_MASK = 0x0001
BAND_80M_MASK = 0x0002
BAND_60M_MASK = 0x0004
BAND_40M_MASK = 0x0008
BAND_30M_MASK = 0x0010
BAND_20M_MASK = 0x0020
BAND_17M_MASK = 0x0040
BAND_15M_MASK = 0x0080
BAND_12M_MASK = 0x0100
BAND_10M_MASK = 0x0200
BAND_6M_MASK = 0x0400
BAND_2M_MASK = 0x0800
BAND_70CM_MASK = 0x1000
BAND_OTHER1_MASK = 0x2000  # not used
BAND_OTHER2_MASK = 0x4000  # not used
BAND_OTHER3_MASK = 0x8000  # not used

# set up message queue
msgq = RingbufQueue(32)

# other I/O setup
onboard = machine.Pin('LED', machine.Pin.OUT, value=1)  # turn on right away
morse_led = machine.Pin(0, machine.Pin.OUT, value=0)  # status/morse code LED on GPIO0 / pin 1
reset_button = machine.Pin(1, machine.Pin.IN, machine.Pin.PULL_UP)  # mode button input on GPIO1 / pin 2

# pushbuttons on display board on GPIO10-13
sw1 = machine.Pin(13, machine.Pin.IN, machine.Pin.PULL_UP)  # mode button input on GPIO13 / pin 17
sw2 = machine.Pin(12, machine.Pin.IN, machine.Pin.PULL_UP)  # mode button input on GPIO12 / pin 16
sw3 = machine.Pin(11, machine.Pin.IN, machine.Pin.PULL_UP)  # mode button input on GPIO11 / pin 15
sw4 = machine.Pin(10, machine.Pin.IN, machine.Pin.PULL_UP)  # mode button input on GPIO10 / pin 14

Button(sw1, msgq, (1, 0), (1, 1))  # SW1
Button(sw2, msgq, (2, 0), (2, 1))
Button(sw3, msgq, (3, 0), (3, 1))
Button(sw4, msgq, (4, 0), (4, 1))  # SW 4

# LCD display on display board on GPIO pins
# RW is hardwired to GPIO7,
machine.Pin(7, machine.Pin.OUT, value=0)
lcd = LCD((8, 6, 5, 4, 3, 2), cols=20)

# radio interface on GPIO15-22
auxbus = machine.Pin(15, machine.Pin.IN, machine.Pin.PULL_UP)  # AUXBUS data input on GPIO15 (maybe)
inhibit = machine.Pin(16, machine.Pin.OUT, value=0)  # TX inhibit control on GPIO16

band0 = machine.Pin(17, machine.Pin.IN, machine.Pin.PULL_UP)  # BAND0 data input on GPIO17
band1 = machine.Pin(18, machine.Pin.IN, machine.Pin.PULL_UP)  # BAND1 data input on GPIO18
band2 = machine.Pin(19, machine.Pin.IN, machine.Pin.PULL_UP)  # BAND2 data input on GPIO19
band3 = machine.Pin(20, machine.Pin.IN, machine.Pin.PULL_UP)  # BAND3 data input on GPIO20

band_detector = FourBits([band3, band2, band1, band0], msgq, (100, 0))
poweron = machine.Pin(21, machine.Pin.IN, machine.Pin.PULL_UP)  # power on control on GPIO21
powersense = machine.Pin(22, machine.Pin.IN, machine.Pin.PULL_UP)  # power sense input on GPIO22
Button(powersense, msgq, (10, 0), (10, 1))
CONFIG_FILE = 'data/config.json'
CONTENT_DIR = 'content/'

PORT_SETTINGS_FILE = 'data/port_settings.txt'

DEFAULT_SECRET = 'band'
DEFAULT_SSID = 'selector'
DEFAULT_WEB_PORT = 80

# globals...
restart = False
keep_running = True
config = {}


def read_config():
    global config
    try:
        with open(CONFIG_FILE, 'r') as config_file:
            config = json.load(config_file)
    except Exception as ex:
        logging.error(f'failed to load configuration:  {type(ex)}, {ex}', 'main:read_config()')
    return config


def save_config(config):
    with open(CONFIG_FILE, 'w') as config_file:
        json.dump(config, config_file)


def default_config():
    return {
        'SSID': 'your_network_ssid',
        'secret': 'your_network_password',
        'web_port': '80',
        'ap_mode': False,
        'dhcp': True,
        'hostname': 'selector1',
        'ip_address': '192.168.1.73',
        'netmask': '255.255.255.0',
        'gateway': '192.168.1.1',
        'dns_server': '8.8.8.8',
        "radio_number": "1",
        "switch_ip": "192.168.1.166",
    }


# noinspection PyUnusedLocal
async def slash_callback(http, verb, args, reader, writer, request_headers=None):  # callback for '/'
    http_status = 301
    bytes_sent = http.send_simple_response(writer, http_status, None, None, ['Location: /switch.html'])
    return bytes_sent, http_status


# noinspection PyUnusedLocal
async def api_config_callback(http, verb, args, reader, writer, request_headers=None):  # callback for '/api/config'
    global config
    if verb == 'GET':
        payload = read_config()
        # payload.pop('secret')  # do not return the secret
        response = json.dumps(payload).encode('utf-8')
        http_status = 200
        bytes_sent = http.send_simple_response(writer, http_status, http.CT_APP_JSON, response)
    elif verb == 'POST':
        config = read_config()
        dirty = False
        errors = False
        # TODO FIXME new config items
        web_port = args.get('web_port')
        if web_port is not None:
            web_port_int = safe_int(web_port, -2)
            if 0 <= web_port_int <= 65535:
                config['web_port'] = web_port
                dirty = True
            else:
                errors = True
        ssid = args.get('SSID')
        if ssid is not None:
            if 0 < len(ssid) < 64:
                config['SSID'] = ssid
                dirty = True
            else:
                errors = True
        secret = args.get('secret')
        if secret is not None:
            if 8 <= len(secret) < 32:
                config['secret'] = secret
                dirty = True
            else:
                errors = True
        ap_mode_arg = args.get('ap_mode')
        if ap_mode_arg is not None:
            ap_mode = True if ap_mode_arg == '1' else False
            config['ap_mode'] = ap_mode
            dirty = True
        dhcp_arg = args.get('dhcp')
        if dhcp_arg is not None:
            dhcp = True if dhcp_arg == 1 else False
            config['dhcp'] = dhcp
            dirty = True
        ip_address = args.get('ip_address')
        if ip_address is not None:
            config['ip_address'] = ip_address
            dirty = True
        netmask = args.get('netmask')
        if netmask is not None:
            config['netmask'] = netmask
            dirty = True
        gateway = args.get('gateway')
        if gateway is not None:
            config['gateway'] = gateway
            dirty = True
        dns_server = args.get('dns_server')
        if dns_server is not None:
            config['dns_server'] = dns_server
            dirty = True
        antenna_bands = args.get('antenna_bands')
        if antenna_bands is not None:
            if len(antenna_bands) == 8:
                config['antenna_bands'] = antenna_bands
                dirty = True
            else:
                errors = True
        antenna_names = args.get('antenna_names')
        if antenna_names is not None:
            if len(antenna_names) == 8:
                config['antenna_names'] = antenna_names
                dirty = True
            else:
                errors = True
        radio_names = args.get('radio_names')
        if radio_names is not None:
            if len(radio_names) == 2:
                config['radio_names'] = radio_names
                dirty = True
            else:
                errors = True
        if not errors:
            if dirty:
                save_config(config)
            response = b'ok\r\n'
            http_status = 200
            bytes_sent = http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
        else:
            response = b'parameter out of range\r\n'
            http_status = 400
            bytes_sent = http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    else:
        response = b'GET or PUT only.'
        http_status = 400
        bytes_sent = http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


# noinspection PyUnusedLocal
async def api_restart_callback(http, verb, args, reader, writer, request_headers=None):
    global keep_running
    if upython:
        keep_running = False
        response = b'ok\r\n'
        http_status = 200
        bytes_sent = http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    else:
        http_status = 400
        response = b'not permitted except on PICO-W'
        bytes_sent = http.send_simple_response(writer, http_status, http.CT_APP_JSON, response)
    return bytes_sent, http_status


async def api_status_callback(http, verb, args, reader, writer, request_headers=None):  # '/api/kpa_status'
    payload = {'radio_number': config['radio_number'],
               'switch_ip': config['switch_ip']}
    response = json.dumps(payload).encode('utf-8')
    http_status = 200
    bytes_sent = http.send_simple_response(writer, http_status, http.CT_APP_JSON, response)
    return bytes_sent, http_status


async def msg_loop(q):
    while True:
        msg = await q.get()
        logging.debug(f'msg received: {msg}')
        m0 = msg[0]
        m1 = msg[1]
        if 1 <= m0 <= 4:
            # button 1-4 on or off.
            # right now I just send a message to the lcd
            await q.put((90, f'button {m0} state {m1}'))
        elif m0 == 90:  # LCD line 1
            lcd[0] = m1
        elif m0 == 91:  # LCD line 2
            lcd[1] = m1
        else:
            logging.warning(f'unhandled message ({m0}, {m1})', 'main:msg_loop')

        # await asyncio.sleep(10)  # don't need, the get (above) is awaited.


async def net_msg_func(message):
    lines = message.split('\n')
    if len(lines) == 1:
        await msgq.put((91, lines[0]))
    else:
        await msgq.put((90, lines[0]))
        await msgq.put((91, lines[1]))


async def main():
    global keep_running, config, restart
    config = read_config()
    if len(config) == 0:
        # create default configuration
        config = default_config()
    web_port = safe_int(config.get('web_port') or DEFAULT_WEB_PORT, DEFAULT_WEB_PORT)
    if web_port < 0 or web_port > 65535:
        web_port = DEFAULT_WEB_PORT
    ap_mode = config.get('ap_mode', False)

    if upython:
        picow_network = PicowNetwork(config, DEFAULT_SSID, DEFAULT_SECRET, net_msg_func)
        morse_code_sender = MorseCode(morse_led)
        morse_sender_task = asyncio.create_task(morse_code_sender.morse_sender())  # TODO move to object init
        msg_loop_task = asyncio.create_task(msg_loop(msgq))

    http_server = HttpServer(content_dir=CONTENT_DIR)
    http_server.add_uri_callback('/', slash_callback)
    http_server.add_uri_callback('/api/config', api_config_callback)
    http_server.add_uri_callback('/api/get_files', api_get_files_callback)
    http_server.add_uri_callback('/api/upload_file', api_upload_file_callback)
    http_server.add_uri_callback('/api/remove_file', api_remove_file_callback)
    http_server.add_uri_callback('/api/rename_file', api_rename_file_callback)
    http_server.add_uri_callback('/api/restart', api_restart_callback)
    http_server.add_uri_callback('/api/status', api_status_callback)

    logging.info(f'Starting web service on port {web_port}', 'main:main')
    web_server = asyncio.create_task(asyncio.start_server(http_server.serve_http_client, '0.0.0.0', web_port))

    reset_button_pressed_count = 0
    while keep_running:
        if upython:
            await asyncio.sleep(0.25)
            pressed = reset_button.value() == 0
            if pressed:
                reset_button_pressed_count += 1
            else:
                if reset_button_pressed_count > 0:
                    reset_button_pressed_count -= 1
            if reset_button_pressed_count > 7:
                logging.info('reset button pressed', 'main:main')
                ap_mode = not ap_mode
                config['ap_mode'] = ap_mode
                save_config(config)
                keep_running = False
        else:
            await asyncio.sleep(10.0)
    if upython:
        machine.soft_reset()


if __name__ == '__main__':
    # logging.loglevel = logging.DEBUG
    logging.loglevel = logging.INFO  # DEBUG
    logging.info('starting', 'main:__main__')
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info('KeyboardInterrupt -- bye bye', 'main:__main__')
    finally:
        asyncio.new_event_loop()
    logging.info('done', 'main:__main__')
