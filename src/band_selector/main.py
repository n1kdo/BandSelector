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
from http_server import (HttpServer,
                         api_rename_file_callback,
                         api_remove_file_callback,
                         api_upload_file_callback,
                         api_get_files_callback)
from morse_code import MorseCode
from picow_network import PicowNetwork
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

# other I/O setup
onboard = machine.Pin('LED', machine.Pin.OUT, value=1)  # turn on right away
morse_led = machine.Pin(0, machine.Pin.OUT, value=0)  # status/morse code LED on GPIO0 / pin 1
reset_button = machine.Pin(1, machine.Pin.IN, machine.Pin.PULL_UP)  # mode button input on GPIO1 / pin 2

# pushbuttons on display board on GPIO10-13
sw1 = machine.Pin(13, machine.Pin.IN, machine.Pin.PULL_UP)  # mode button input on GPIO13 / pin 17
sw2 = machine.Pin(12, machine.Pin.IN, machine.Pin.PULL_UP)  # mode button input on GPIO12 / pin 16
sw3 = machine.Pin(11, machine.Pin.IN, machine.Pin.PULL_UP)  # mode button input on GPIO11 / pin 15
sw4 = machine.Pin(10, machine.Pin.IN, machine.Pin.PULL_UP)  # mode button input on GPIO10 / pin 14

# LCD display on display board on GPIO pins
# RW is hardwired to GPIO7,
machine.Pin(7, machine.Pin.OUT, value=0)
lcd = LCD((8, 6, 5, 4, 3, 2), cols=20)

# radio interface on GPIO15-22
auxbus = machine.Pin(15, machine.Pin.IN, machine.Pin.PULL_UP)  # AUXBUS data input on GPIO15
inhibit = machine.Pin(16, machine.Pin.OUT, value=0)  # TX inhibit control on GPIO16
band0 = machine.Pin(17, machine.Pin.IN, machine.Pin.PULL_UP)  # BAND0 data input on GPIO17
band1 = machine.Pin(18, machine.Pin.IN, machine.Pin.PULL_UP)  # BAND1 data input on GPIO18
band2 = machine.Pin(19, machine.Pin.IN, machine.Pin.PULL_UP)  # BAND2 data input on GPIO19
band3 = machine.Pin(20, machine.Pin.IN, machine.Pin.PULL_UP)  # BAND3 data input on GPIO20
poweron = machine.Pin(21, machine.Pin.IN, machine.Pin.PULL_UP)  # power on control on GPIO21
powersense = machine.Pin(22, machine.Pin.IN, machine.Pin.PULL_UP)  # power sense input on GPIO22

CONFIG_FILE = 'data/config.json'
CONTENT_DIR = 'content/'

PORT_SETTINGS_FILE = 'data/port_settings.txt'

DEFAULT_SECRET = 'antenna'
DEFAULT_SSID = 'switch'
DEFAULT_TCP_PORT = 73
DEFAULT_WEB_PORT = 80

# globals...
restart = False
antennas_selected = [1, 2]
keep_running = True
config = {}


def read_antennas_selected() -> []:
    result = [1, 2]
    try:
        with open(PORT_SETTINGS_FILE, 'r') as port_settings_file:
            result[0] = safe_int(port_settings_file.readline().strip())
            result[1] = safe_int(port_settings_file.readline().strip())
    except OSError:
        logging.warning(f'failed to load selected antenna data, returning defaults.', 'main:read_port_selected()')
    except Exception as ex:
        logging.error(f'failed to load selected antenna data: {type(ex)}, {ex}', 'main:read_port_selected()')
    logging.info(f'read antennas selected: {result[0]}, {result[1]}')
    return result


def write_antennas_selected(antennas_selected):
    try:
        with open(PORT_SETTINGS_FILE, 'w') as port_settings_file:
            port_settings_file.write(f'{antennas_selected[0]}\n')
            port_settings_file.write(f'{antennas_selected[1]}\n')
    except Exception as ex:
        logging.error(f'failed to write selected antenna data: {type(ex)}, {ex}',
                      'main:write_antennas_selected()')
    return


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
        'tcp_port': '73',
        'web_port': '80',
        'ap_mode': False,
        'dhcp': True,
        'hostname': 'ant-switch',
        'ip_address': '192.168.1.73',
        'netmask': '255.255.255.0',
        'gateway': '192.168.1.1',
        'dns_server': '8.8.8.8',
        'port_bands': [0, 0, 0, 0, 0, 0, 0, 0],
        'port_names': ['not set', 'not set', 'not set', 'not set', 'not set', 'not set', 'not set', 'not set'],
        'radio_names': ['Radio 1', 'Radio 2']
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
        tcp_port = args.get('tcp_port')
        if tcp_port is not None:
            tcp_port_int = safe_int(tcp_port, -2)
            if 0 <= tcp_port_int <= 65535:
                config['tcp_port'] = tcp_port
                dirty = True
            else:
                errors = True
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
    payload = {'radio_1_antenna': antennas_selected[0],
               'radio_2_antenna': antennas_selected[1],
               'radio_names': config['radio_names'],
               'antenna_names': config['antenna_names']}
    response = json.dumps(payload).encode('utf-8')
    http_status = 200
    bytes_sent = http.send_simple_response(writer, http_status, http.CT_APP_JSON, response)
    return bytes_sent, http_status


async def api_select_antenna_callback(http, verb, args, reader, writer, request_headers=None):
    global antennas_selected
    radio = safe_int(args.get('radio', '0'))
    antenna_requested = safe_int(args.get('antenna', '0'))
    if 1 <= radio <= 2 and 1 <= antenna_requested <= 8:
        other_radio = 2 if radio == 1 else 1
        if antenna_requested == antennas_selected[other_radio-1]:
            http_status = 409
            response = b'That antenna is in use.\r\n'
        else:
            antennas_selected[radio - 1] = antenna_requested
            logging.debug(f'calling set_port({radio}, {antenna_requested})')
            # set_port(radio, antenna_requested)
            write_antennas_selected(antennas_selected)
            http_status = 200
            response = b'ok\r\n'
    else:
        response = b'Bad radio or antenna parameter\r\n'
        http_status = 400
    bytes_sent = http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


async def serve_serial_client(reader, writer):
    """
    send the data over a dumb connection
    """
    t0 = milliseconds()
    partner = writer.get_extra_info('peername')[0]
    logging.info(f'client connected from {partner}', 'main:serve_serial_client')
    client_connected = True

    try:
        while client_connected:
            data = await reader.read(1)
            if data is None:
                break
            else:
                if len(data) == 1:
                    b = data[0]
                    if b == 10:  # line feed, get status
                        payload = {'radio_1_port': antennas_selected[0], 'radio_2_port': antennas_selected[1]}
                        response = (json.dumps(payload) + '\n').encode('utf-8')
                        writer.write(response)
                    elif b == 4 or b == 26 or b == 81 or b == 113:  # ^D/^z/q/Q exit
                        client_connected = False
                    await writer.drain()

        reader.close()
        writer.close()
        await writer.wait_closed()

    except Exception as ex:
        logging.error(f'exception in serve_serial_client: {type(ex)}, {ex}', 'main:serve_serial_client')
    tc = milliseconds()
    logging.info(f'client disconnected, elapsed time {(tc - t0) / 1000.0:6.3f} seconds', 'main:serve_serial_client')


async def main():
    global antennas_selected, keep_running, config, restart
    antennas_selected = read_antennas_selected()
    logging.debug(f'calling set_port(1, {antennas_selected[0]})')
    #set_port(1, antennas_selected[0])
    logging.debug(f'calling set_port(2, {antennas_selected[1]})')
    #set_port(2, antennas_selected[1])
    config = read_config()
    if len(config) == 0:
        # create default configuration
        config = default_config()
    tcp_port = safe_int(config.get('tcp_port') or DEFAULT_TCP_PORT, DEFAULT_TCP_PORT)
    if tcp_port < 0 or tcp_port > 65535:
        tcp_port = DEFAULT_TCP_PORT
    web_port = safe_int(config.get('web_port') or DEFAULT_WEB_PORT, DEFAULT_WEB_PORT)
    if web_port < 0 or web_port > 65535:
        web_port = DEFAULT_WEB_PORT

    ap_mode = config.get('ap_mode', False)

    if upython:
        picow_network = PicowNetwork(config, DEFAULT_SSID, DEFAULT_SECRET)
        network_keepalive_task = asyncio.create_task(picow_network.keep_alive())
        morse_code_sender = MorseCode(morse_led)
        morse_sender_task = asyncio.create_task(morse_code_sender.morse_sender())



    http_server = HttpServer(content_dir=CONTENT_DIR)
    http_server.add_uri_callback('/', slash_callback)
    http_server.add_uri_callback('/api/config', api_config_callback)
    http_server.add_uri_callback('/api/get_files', api_get_files_callback)
    http_server.add_uri_callback('/api/upload_file', api_upload_file_callback)
    http_server.add_uri_callback('/api/remove_file', api_remove_file_callback)
    http_server.add_uri_callback('/api/rename_file', api_rename_file_callback)
    http_server.add_uri_callback('/api/restart', api_restart_callback)
    http_server.add_uri_callback('/api/status', api_status_callback)
    http_server.add_uri_callback('/api/select_antenna', api_select_antenna_callback)

    logging.info(f'Starting web service on port {web_port}', 'main:main')
    web_server = asyncio.create_task(asyncio.start_server(http_server.serve_http_client, '0.0.0.0', web_port))
    logging.info(f'Starting tcp service on port {tcp_port}', 'main:main')
    tcp_server = asyncio.create_task(asyncio.start_server(serve_serial_client, '0.0.0.0', tcp_port))

    reset_button_pressed_count = 0
    last_message = ''
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
            if picow_network.get_message() != last_message:
                last_message = picow_network.get_message()
                morse_code_sender.set_message(last_message)
            buts = ('1 ' if not sw1.value() else '  ') + \
                   ('2 ' if not sw2.value() else '  ') + \
                   ('3 ' if not sw3.value() else '  ') + \
                   ('4 ' if not sw4.value() else '  ')
            lcd[0] = f'buttons : {buts:>10s}'
            lcd[1] = f'{last_message:^20s}'
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
