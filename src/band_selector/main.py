#
# main.py -- this is the web server for the Raspberry Pi Pico W Band Selector controller.
#

__author__ = 'J. B. Otterson'
__copyright__ = 'Copyright 2022, 2024 J. B. Otterson N1KDO.'
__version__ = '0.0.2'

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
from ringbuf_queue import RingbufQueue
from utils import milliseconds, upython, safe_int, num_bits_set
import micro_logging as logging

if upython:
    import machine
    import network
    import uasyncio as asyncio
    from uasyncio import sleep
    from picow_network import PicowNetwork
else:
    import asyncio
    from not_machine import machine
    from asyncio import sleep

import uaiohttpclient as aiohttp


BANDS = ['NoBand', '160M',  '80M',  '60M',  '40M',  '30M',  '20M',  '17M',  '15M',  '12M',  '10M',   '6M',  '2M', '70cm', 'NoBand', 'NoBand']
MASKS = [  0x0000, 0x0001, 0x0002, 0x0004, 0x0008, 0x0010, 0x0020, 0x0040, 0x0080, 0x0100, 0x0200, 0x0400, 0x800, 0x1000,   0x0000,   0x0000]
#               0       1       2       3       4       5       6       7        8      9      10      11     12      13        14        15

# this list maps band indexes to the value of the 4-bit band select outputs.
# there are 11 valid outputs, 0000 -> 1010 (0-10), the other four will return NO BAND (0)
ELECRAFT_BAND_MAP = [3,  # 0000 -> 60M
                     1,  # 0001 -> 160M
                     2,  # 0010 -> 80M
                     4,  # 0011 -> 40M
                     5,  # 0100 -> 30M
                     6,  # 0101 -> 20M
                     7,  # 0110 -> 17M
                     8,  # 0111 -> 15M
                     9,  # 1000 -> 12M
                     10, # 1001 -> 10M
                     11, # 1010 ->  6M
                     0,  # 1011 -> invalid
                     0,  # 1100 -> invalid
                     0,  # 1101 -> invalid
                     0,  # 1110 -> invalid
                     0,  # 1111 -> invalid
                     ]

# message IDs
MSG_BTN_1 = 1
MSG_BTN_2 = 2
MSG_BTN_3 = 3
MSG_BTN_4 = 4
MSG_POWER_SENSE = 10
MSG_NETWORK_CHANGE = 20
MSG_NETWORK_UPDOWN = 50
MSG_LCD_LINE0 = 90
MSG_LCD_LINE1 = 91
MSG_BAND_CHANGE = 100
MSG_STATUS_RESPONSE = 201
MSG_ANTENNA_RESPONSE = 202

# set up message queue
msgq = RingbufQueue(32)

# other I/O setup
onboard = machine.Pin('LED', machine.Pin.OUT, value=1)  # turn on right away
red_led = machine.Pin(0, machine.Pin.OUT, value=0)  # Red LED on GPIO0 / pin 1
#   reset_button = machine.Pin(1, machine.Pin.IN, machine.Pin.PULL_UP)  # mode button input on GPIO1 / pin 2

# push buttons on display board on GPIO10-13
sw1 = machine.Pin(13, machine.Pin.IN, machine.Pin.PULL_UP)  # mode button input on GPIO13 / pin 17
sw2 = machine.Pin(12, machine.Pin.IN, machine.Pin.PULL_UP)  # mode button input on GPIO12 / pin 16
sw3 = machine.Pin(11, machine.Pin.IN, machine.Pin.PULL_UP)  # mode button input on GPIO11 / pin 15
sw4 = machine.Pin(10, machine.Pin.IN, machine.Pin.PULL_UP)  # mode button input on GPIO10 / pin 14

Button(sw1, msgq, (MSG_BTN_1, 0), (MSG_BTN_1, 1))  # SW1
Button(sw2, msgq, (MSG_BTN_2, 0), (MSG_BTN_2, 1))
Button(sw3, msgq, (MSG_BTN_3, 0), (MSG_BTN_3, 1))
Button(sw4, msgq, (MSG_BTN_4, 0), (MSG_BTN_4, 1))  # SW 4

# LCD display on display board on GPIO pins
# RW is hardwired to GPIO7,
machine.Pin(7, machine.Pin.OUT, value=0)  # this is the RW pin, hold it low.
light = machine.Pin(9, machine.Pin.OUT, value=1)  # this is the backlight, so I can blink it.
lcd = LCD((8, 6, 5, 4, 3, 2), cols=20)

# radio interface on GPIO15-22
# auxbus = machine.Pin(15, machine.Pin.IN, machine.Pin.PULL_UP)  # AUXBUS data input on GPIO15 (maybe)
inhibit_pin = machine.Pin(16, machine.Pin.OUT, value=0)  # TX inhibit control on GPIO16

band0 = machine.Pin(17, machine.Pin.IN, machine.Pin.PULL_UP)  # BAND0 data input on GPIO17
band1 = machine.Pin(18, machine.Pin.IN, machine.Pin.PULL_UP)  # BAND1 data input on GPIO18
band2 = machine.Pin(19, machine.Pin.IN, machine.Pin.PULL_UP)  # BAND2 data input on GPIO19
band3 = machine.Pin(20, machine.Pin.IN, machine.Pin.PULL_UP)  # BAND3 data input on GPIO20

band_detector = FourBits([band3, band2, band1, band0], msgq, (MSG_BAND_CHANGE, 0))
poweron_pin = machine.Pin(21, machine.Pin.OUT, value=0)  # power on control on GPIO21
powersense = machine.Pin(22, machine.Pin.IN, machine.Pin.PULL_UP)  # power sense input on GPIO22

Button(powersense, msgq, (MSG_POWER_SENSE, 0), (MSG_POWER_SENSE, 1))

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
current_antenna = -1
current_antenna_name = 'unknown antenna'
current_band_number = 0
radio_name = 'unknown radio'
antenna_names = []
antenna_bands = []
band_antennae = []  # list of antennas that could work on the current band.
radio_power = False


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
        'radio_number': '1',
        'switch_ip': '192.168.1.166',
    }


async def api_response(resp, msg, msgq):
    """
    function waits for API response, enqueues message containing response
    :param resp: the HTTP response data from the API call
    :param msg: a "prototype" for the message to be returned.  a 2-tuple, (MSG_ID, payload)
    :param msgq: the message queue on which to enqueue the message
    :return: None
    """
    payload = await resp.read()
    await resp.aclose()
    logging.debug(f'api call returned {payload}', 'main:api_response')
    data = (msg[1][0], payload)  # copy the existing http status from the msg tuple
    new_msg = (msg[0], data)
    await msgq.put(new_msg)


async def call_api(config, endpoint, msg, msgq):
    # TODO this is too slow. but it does work.
    t0 = milliseconds()
    url = f'http://{config.get('switch_ip', 'localhost')}{endpoint}'
    logging.info(f'calling api {url} at {milliseconds()}', 'main:call_api')
    #resp = yield from aiohttp.request("GET", url)
    resp = await aiohttp.request("GET", url)
    http_status = resp.status
    t1 = milliseconds()
    logging.info(f'api call to {endpoint} took {t1 - t0} ms', 'main:call_api')
    msg = (msg[0], (http_status, 'no response'))
    asyncio.create_task(api_response(resp, msg, msgq))


async def call_select_antenna_api(config, new_antenna, msg, msgq):
    radio_number = config.get('radio_number')
    logging.debug(f'attempting to select antenna {new_antenna}', 'main:call_select_antenna_api')
    endpoint = f'/api/select_antenna?radio={radio_number}&antenna={new_antenna}'
    await call_api(config, endpoint, msg, msgq)


# noinspection PyUnusedLocal
async def slash_callback(http, verb, args, reader, writer, request_headers=None):  # callback for '/'
    http_status = 301
    bytes_sent = http.send_simple_response(writer, http_status, None, None, ['Location: /status.html'])
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
        switch_ip = args.get('switch_ip')
        if switch_ip is not None:
            config['switch_ip'] = switch_ip
            dirty = True
        radio_number = safe_int(args.get('radio_number'), -1)
        if radio_number is not None:
            if 1 <= radio_number <= 2:
                config['radio_number'] = radio_number
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
        bytes_sent = http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


async def api_status_callback(http, verb, args, reader, writer, request_headers=None):  # '/api/kpa_status'
    payload = {'lcd_lines': [lcd[0], lcd[1]]}
    response = json.dumps(payload).encode('utf-8')
    http_status = 200
    bytes_sent = http.send_simple_response(writer, http_status, http.CT_APP_JSON, response)
    return bytes_sent, http_status


async def api_power_on_radio_callback(http, verb, args, reader, writer, request_headers=None):
    await power_on()
    response = b'ok'
    http_status = 200
    bytes_sent = http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status

def find_band_antennae(new_band_number: int) -> [int]:
    antennas = []
    mask = MASKS[new_band_number]
    bands = 1
    # get a list of antennas for this band with the list sorted from the antenna with the fewest other bands
    while bands < len(BANDS):
        for i in range(0, len(antenna_bands)):
            if mask & antenna_bands[i] and num_bits_set(antenna_bands[i]) == bands:
                antennas.append(i)
        bands += 1
    return antennas


def set_inhibit(inhibit):
    inhibit_pin.value(inhibit)
    red_led.value(inhibit)  #  TODO FIXME DEBUG


async def power_on():
    poweron_pin.on()
    await sleep(0.100)
    poweron_pin.off()


async def new_band(new_band_number):
    global band_antennae
    logging.info(f'new band: {BANDS[new_band_number]}', 'main:new_band')
    await msgq.put((MSG_LCD_LINE0, f'{radio_name} {BANDS[new_band_number]}'))
    set_inhibit(1)
    band_antennae = find_band_antennae(new_band_number)
    if len(band_antennae) == 0:
        logging.warning(f'no antenna available for band {BANDS[new_band_number]}', 'main:new_band')
        #                              '12345678901234567890'
        await msgq.put((MSG_LCD_LINE1, '*No Antenna for Band'))
    else:
        await msgq.put((MSG_LCD_LINE1, ''))  # erase the line
        await call_select_antenna_api(config, band_antennae.pop(0) + 1, (202, (0, '')), msgq)


async def msg_loop(q):
    global current_antenna, current_antenna_name, current_band_number, radio_name, antenna_names, antenna_bands, band_antennae, radio_power
    while True:
        msg = await q.get()
        t0 = milliseconds()
        logging.debug(f'msg received: {msg}', 'main:msg_loop')
        m0 = msg[0]
        m1 = msg[1]
        if MSG_BTN_1 <= m0 <= MSG_BTN_2:
            # button 1-2 on or off.
            # right now I just send a message to the lcd
            await q.put((MSG_LCD_LINE0, f'button {m0} state {m1}'))
        elif m0 == MSG_BTN_3:
            if m1 == 0:
                current_band_number += 1
                if current_band_number >= len(BANDS):
                    current_band_number = 1
                await new_band(current_band_number)
        elif m0 == MSG_BTN_4:
            if m1 == 0:
                current_band_number -= 1
                if current_band_number < 1:
                    current_band_number = len(BANDS) -1
                await new_band(current_band_number)
        elif m0 == MSG_POWER_SENSE:  # power sense changed
            if m1 == 0:
                # detect missing radio.  do something about it.
                radio_power = True
            else:
                radio_power = False

        elif m0 == MSG_NETWORK_UPDOWN:
            # network up/down
            if m1 == 1: # network is up!
                logging.info('Network is up!', 'main:msg_loop')
                await call_api(config, '/api/status', (201, None), msgq)
        elif m0 == MSG_LCD_LINE0:  # LCD line 1
            lcd[0] = f'{m1:^20s}'
            logging.info(f'LCD0: "{lcd[0]}"', 'main:msg_loop')
            await asyncio.sleep_ms(50)
        elif m0 == MSG_LCD_LINE1:  # LCD line 2
            lcd[1] = f'{m1:^20s}'
            logging.info(f'LCD1: "{lcd[1]}"', 'main:msg_loop')
            await asyncio.sleep_ms(50)
        elif m0 == MSG_BAND_CHANGE:  # band change detected
            logging.debug(f'band change, power = {radio_power}', 'main:msg_loop')
            if not radio_power:
                m1 = -2
            #logging.info(f'band change, sense = {m1}', 'main:msg_loop')
            if 0 <= m1 <= len(ELECRAFT_BAND_MAP):
                current_band_number = ELECRAFT_BAND_MAP[m1]
                if len(antenna_names) > 0:  # only change bands if there are antennas.
                    await new_band(current_band_number)
            else:
                await msgq.put((MSG_LCD_LINE0, f'{radio_name} not found'))
                set_inhibit(1)

        elif m0 == MSG_STATUS_RESPONSE:  # http status response
            http_status = m1[0]
            try:
                switch_data = json.loads(m1[1])
            except json.decoder.JSONDecodeError as jde:
                logging.exception('cannot decode json', 'main:msg_loop', jde)
                switch_data = {}
            antenna_names = switch_data.get('antenna_names', ['','','','','','','',''])
            antenna_bands = switch_data.get('antenna_bands', [0, 0, 0, 0, 0, 0, 0, 0])
            radio_names = switch_data.get('radio_names', ['unknown radio', 'unknown radio'])
            radio_number = int(config.get('radio_number', -1))
            radio_name = radio_names[radio_number-1]
            current_antenna = -1
            if radio_number == 1:
                current_antenna = switch_data.get('radio_1_antenna', -1)
            elif radio_number == 2:
                current_antenna = switch_data.get('radio_2_antenna', -1)
            if 1 <= current_antenna <= 8:
                current_antenna_name = antenna_names[current_antenna - 1]
            else:
                current_antenna_name = f'unknown antenna {current_antenna}'
            await msgq.put((MSG_LCD_LINE1, current_antenna_name))

            if not radio_power:
                await msgq.put((MSG_LCD_LINE0, f'{radio_name} no radio'))
                set_inhibit(1)
            else:
                await msgq.put((MSG_LCD_LINE0, radio_name + ' ' + BANDS[current_band_number]))
                if current_antenna == -1:
                    set_inhibit(1)
                else:
                    if MASKS[current_band_number] & antenna_bands[current_antenna-1]:
                        set_inhibit(0)
                        await msgq.put((MSG_LCD_LINE1, current_antenna_name))
                    else:
                        set_inhibit(1)
                        # try to get the right band...
                        await new_band(current_band_number)
        elif m0 == MSG_ANTENNA_RESPONSE:  # http select antenna response
            http_status = m1[0]
            payload = m1[1].decode().strip()
            if http_status == 200:
                await call_api(config, '/api/status', (201, None), msgq)
            elif 400 <= http_status <= 499:
                if len(band_antennae) == 0:
                    # logging.warning(f'no antenna available for band {BANDS[new_band_number]}')
                    await msgq.put((MSG_LCD_LINE1, f'*{payload}'))
                    set_inhibit(1)
                else:
                    # if there is another antenna candidate, try to get it
                    await msgq.put((MSG_LCD_LINE1, ''))  # erase the line
                    await call_select_antenna_api(config, band_antennae.pop(0) + 1, (202, (0, '')), msgq)
        else:
            logging.warning(f'unhandled message ({m0}, {m1})', 'main:msg_loop')
        t1 = milliseconds()
        if logging.loglevel == logging.DEBUG:
            logging.debug(f'   Message {m0} handling took {t1-t0} ms.', 'main:msg_loop')


async def net_msg_func(message:str, msg_status=0) -> None:
    logging.debug(f'network message: "{message.strip()}", {msg_status}', 'main:net_msg_func')
    lines = message.split('\n')
    if len(lines) == 1:
        await msgq.put((MSG_LCD_LINE1, lines[0]))
    else:
        await msgq.put((MSG_LCD_LINE0, lines[0]))
        await msgq.put((MSG_LCD_LINE1, lines[1]))
    if msg_status == network.STAT_GOT_IP:
        await msgq.put((MSG_NETWORK_UPDOWN, 1))


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
    http_server.add_uri_callback('/api/power_on_radio', api_power_on_radio_callback)

    logging.info(f'Starting web service on port {web_port}', 'main:main')
    web_server = asyncio.create_task(asyncio.start_server(http_server.serve_http_client, '0.0.0.0', web_port))

    reset_button_pressed_count = 0
    while keep_running:
        if upython:
            await asyncio.sleep(0.25)
            pressed = False  # TODO FIXME cannot reset right now  reset_button.value() == 0
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
    logging.loglevel = logging.DEBUG  # TODO FIXME
    logging.loglevel = logging.INFO
    logging.info('starting', 'main:__main__')
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info('KeyboardInterrupt -- bye bye', 'main:__main__')
    finally:
        asyncio.new_event_loop()
    logging.info('done', 'main:__main__')
