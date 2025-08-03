#
# main.py -- this is the web server for the Raspberry Pi Pico W Band Selector controller.
#

__author__ = 'J. B. Otterson'
__copyright__ = 'Copyright 2022, 2024, 2025 J. B. Otterson N1KDO.'
__version__ = '0.1.10'

#
# Copyright 2022, 2024, 2025 J. B. Otterson N1KDO.
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

import asyncio
import gc
import json
import sys
import time

from alcd import LCD
from button import Button
from fourbits import FourBits
from gpio_pin import GPIO_Pin
from http_server import (HttpServer,
                         api_rename_file_callback,
                         api_remove_file_callback,
                         api_upload_file_callback,
                         api_get_files_callback,
                         HTTP_STATUS_OK,
                         HTTP_STATUS_BAD_REQUEST,
                         HTTP_VERB_GET,
                         HTTP_VERB_POST)

import micro_logging as logging
from ntp import get_ntp_time
from ringbuf_queue import RingbufQueue
from utils import milliseconds, upython, safe_int, num_bits_set

if upython:
    import machine
    from picow_network import PicowNetwork
    from watchdog import Watchdog
else:
    from not_machine import machine

    def const(i):  # support micropython const() in cpython
        return i

import uaiohttpclient as aiohttp

BANDS = ['NoBand', '160M', '80M', '60M', '40M', '30M', '20M', '17M', '15M', '12M', '10M', '6M', '2M', '70cm', 'NoBand',
         'NoBand']
MASKS = [0x0000, 0x0001, 0x0002, 0x0004, 0x0008, 0x0010, 0x0020, 0x0040, 0x0080, 0x0100, 0x0200, 0x0400, 0x800, 0x1000,
         0x0000, 0x0000]
_MIN_BAND = const(1)
_MAX_BAND = const(13)

# this list maps band indexes to the value of the 4-bit band select outputs.
# there are 11 valid outputs, 0000 -> 1010 (0-10), the other five map to NO BAND (0)
ELECRAFT_BAND_MAP = [3,  # 0000 -> 60M
                     1,  # 0001 -> 160M
                     2,  # 0010 -> 80M
                     4,  # 0011 -> 40M
                     5,  # 0100 -> 30M
                     6,  # 0101 -> 20M
                     7,  # 0110 -> 17M
                     8,  # 0111 -> 15M
                     9,  # 1000 -> 12M
                     10,  # 1001 -> 10M
                     11,  # 1010 ->  6M
                     0,  # 1011 -> invalid
                     0,  # 1100 -> invalid
                     0,  # 1101 -> invalid
                     0,  # 1110 -> invalid
                     0,  # 1111 -> invalid
                     ]

# message IDs
_MSG_BTN_1 = const(1)
_MSG_BTN_2 = const(2)
_MSG_BTN_3 = const(3)
_MSG_BTN_4 = const(4)
_MSG_POWER_SENSE = const(10)
_MSG_NETWORK_CHANGE = const(20)
_MSG_NETWORK_UPDOWN = const(50)
_MSG_CONFIG_CHANGE = const(60)
_MSG_LCD_LINE0 = const(90)
_MSG_LCD_LINE1 = const(91)
_MSG_BAND_CHANGE = const(100)
_MSG_STATUS_RESPONSE = const(201)
_MSG_ANTENNA_RESPONSE = const(202)

# http api status for failures
_API_STATUS_TIMEOUT = const(-1)
_API_STATUS_ERROR = const(-2)
_API_STATUS_READ_ERROR = const(-3)

# set up message queue
msgq = RingbufQueue(32)

# other I/O setup
onboard = machine.Pin('LED', machine.Pin.OUT, value=1)  # turn on right away
red_led = machine.Pin(0, machine.Pin.OUT, value=0)  # Red LED on GPIO0 / pin 1

# push buttons on display board on GPIO10-13
sw1 = machine.Pin(13, machine.Pin.IN, machine.Pin.PULL_UP)  # mode button input on GPIO13 / pin 17
sw2 = machine.Pin(12, machine.Pin.IN, machine.Pin.PULL_UP)  # mode button input on GPIO12 / pin 16
sw3 = machine.Pin(11, machine.Pin.IN, machine.Pin.PULL_UP)  # mode button input on GPIO11 / pin 15
sw4 = machine.Pin(10, machine.Pin.IN, machine.Pin.PULL_UP)  # mode button input on GPIO10 / pin 14

Button(sw1, msgq, (_MSG_BTN_1, 0), (_MSG_BTN_1, 1))  # SW1
Button(sw2, msgq, (_MSG_BTN_2, 0), (_MSG_BTN_2, 1))
Button(sw3, msgq, (_MSG_BTN_3, 0), (_MSG_BTN_3, 1))
Button(sw4, msgq, (_MSG_BTN_4, 0), (_MSG_BTN_4, 1))  # SW 4

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
band_detector = FourBits([band3, band2, band1, band0], msgq, (_MSG_BAND_CHANGE, 0))
poweron_pin = machine.Pin(21, machine.Pin.OUT, value=0)  # power on control on GPIO21
powersense = machine.Pin(22, machine.Pin.IN, machine.Pin.PULL_UP)  # power sense input on GPIO22
GPIO_Pin(powersense, msgq, (_MSG_POWER_SENSE, 0), (_MSG_POWER_SENSE, 1))

CONFIG_FILE = 'data/config.json'
CONTENT_DIR = 'content/'

PORT_SETTINGS_FILE = 'data/port_settings.txt'

DEFAULT_SECRET = 'selector'
DEFAULT_SSID = 'selector'
DEFAULT_WEB_PORT = 80

# globals...
restart = False
keep_running = True
config = {}
current_antenna = -1
current_antenna_name = 'Unknown Antenna'
current_band_number = 0
radio_name = 'Unknown Rig'
antenna_names = []
antenna_bands = []
band_antennae = []  # list of antennas that could work on the current band.
network_connected = False
radio_number = 0
radio_power = False
switch_connected = False
switch_host = None
switch_poll_delay = 30
switch_timeouts = 0

# well-loved status messages
radio_status = ['', '']
network_status = ['', '']

# menu state machine data
_RADIO_STATUS_STATE = const(0)
_NETWORK_STATUS_STATE = const(1)
_MENU_MODE_STATE = const(2)
_MENU_EDIT_STATE = const(3)
MENUS = [
    ('Network Mode', ['Station', 'Access Point']),
    ('Restart?', ['No', 'Yes']),
]

menu_state = _RADIO_STATUS_STATE
current_antenna_list_index = 0

def select_restart_mode(mode):
    global restart, keep_running
    if mode:
        restart = True
        keep_running = False


def read_config():
    global config
    try:
        with open(CONFIG_FILE, 'r') as config_file:
            config = json.load(config_file)
    except Exception as ex:
        logging.error(f'failed to load configuration:  {type(ex)}, {ex}', 'main:read_config()')
    return config


def save_config(config_data):
    with open(CONFIG_FILE, 'w') as config_file:
        json.dump(config_data, config_file)


def default_config():
    return {
        'SSID': 'your_network_ssid',
        'secret': 'your_network_password',
        'web_port': '80',
        'ap_mode': False,
        'dhcp': True,
        'hostname': 'selector1',
        'ip_address': '192.168.1.73',
        'log_level': 'debug',
        'netmask': '255.255.255.0',
        'gateway': '192.168.1.1',
        'dns_server': '8.8.8.8',
        'radio_number': '1',
        'switch_ip': '192.168.1.166',
        'poll_delay': '10',
    }


async def api_response(resp, msg, q):
    """
    function waits for API response, enqueues message containing response
    :param resp: the HTTP response data from the API call
    :param msg: a "prototype" for the message to be returned.  a 2-tuple, (MSG_ID, payload)
    :param q: the message queue on which to enqueue the message
    :return: None
    """
    status = msg[1][0]
    try:
        payload = await resp.read()
    except Exception as ex:
        logging.exception('did not read payload', 'main:api_response', ex)
        payload = b'api read error'
        status = _API_STATUS_READ_ERROR
    if logging.should_log(logging.DEBUG):
        logging.debug(f'api call returned {payload}', 'main:api_response')
    data = (status, payload)  # copy the existing http status from the msg tuple
    new_msg = (msg[0], data)
    await q.put(new_msg)


async def call_api(url, msg, q):
    if logging.should_log(logging.DEBUG):
        logging.debug(f'calling api {url}', 'main:call_api')
    gc.collect()
    if upython and logging.should_log(logging.DEBUG):
        free = gc.mem_free()
        alloc = gc.mem_alloc()
        pct_free = free/(free + alloc) * 100
        logging.debug(f'{alloc} allocated, {free} free {pct_free:6.2f}% free.', 'main:call_api')
    t0 = milliseconds()
    try:
        resp = await asyncio.wait_for(aiohttp.request("GET", url), 0.5)
    except asyncio.TimeoutError:  # as ex:
        dt = milliseconds() - t0
        errmsg = b'timed out on api call to "%s" after %d ms' % (url, dt)
        logging.warning(errmsg, 'main:call_api')
        msg = (msg[0], (_API_STATUS_TIMEOUT, errmsg))
        await q.put(msg)
    except Exception as ex:
        dt = milliseconds() - t0
        errmsg = b'failed to execute api call to "%s" after %d ms' % (url, dt)
        logging.exception(errmsg, 'main:call_api', ex)
        msg = (msg[0], (_API_STATUS_ERROR, errmsg))
        await q.put(msg)
    else:
        http_status = resp.status
        if logging.should_log(logging.INFO):
            dt = milliseconds() - t0
            logging.info(f'api call to {url} returned {http_status} after {dt} ms', 'main:call_api')
        msg = (msg[0], (http_status, 'no response'))
        asyncio.create_task(api_response(resp, msg, q))


async def call_select_antenna_api(new_antenna, msg, q):
    if logging.should_log(logging.INFO):
        logging.info(f'requesting antenna {new_antenna}', 'main:call_select_antenna_api')
    url = b'http://%s/api/select_antenna?radio=%d&antenna=%d' % (switch_host, radio_number, new_antenna)
    asyncio.create_task(call_api(url, msg, q))


async def call_status_api(param_radio_number, msg, q):
    if param_radio_number == 1 or param_radio_number == 2:
        url = b'http://%s/api/status?radio=%d' % (switch_host, param_radio_number)
    else:
        url = b'http://%s/api/status' % (switch_host)
    asyncio.create_task(call_api(url, msg, q))


# noinspection PyUnusedLocal
async def slash_callback(http, verb, args, reader, writer, request_headers=None):  # callback for '/'
    http_status = 301
    bytes_sent = await http.send_simple_response(writer, http_status, None, None, ['Location: /status.html'])
    return bytes_sent, http_status


# noinspection PyUnusedLocal
async def api_config_callback(http, verb, args, reader, writer, request_headers=None):  # callback for '/api/config'
    global config, switch_host, switch_poll_delay, radio_number
    if verb == HTTP_VERB_GET:
        response = read_config()
        # response.pop('secret')  # do not return the secret
        response['secret'] = ''  # do not return the actual secret
        http_status = HTTP_STATUS_OK
        bytes_sent = await http.send_simple_response(writer, http_status, http.CT_APP_JSON, response)
    elif verb == HTTP_VERB_POST:
        # TODO FIXME look at state of ap_mode, only allow some changes when in ap_mode.
        config = read_config()
        ap_mode = config.get('ap_mode', False)
        dirty = False
        errors = False
        problems = []
        log_level = args.get('log_level')
        if log_level is not None:
            log_level = log_level.strip().upper()
            if log_level in ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL', 'NONE']:
                config['log_level'] = log_level
                logging.set_level(log_level)
                dirty = True
            else:
                errors = True
                problems.append('log_level')
        web_port = args.get('web_port')
        if web_port is not None:
            web_port_int = safe_int(web_port, -2)
            if 0 <= web_port_int <= 65535:
                config['web_port'] = web_port
                dirty = True
            else:
                errors = True
                problems.append('web_port')
        ssid = args.get('SSID')
        if ssid is not None:
            if 0 < len(ssid) < 64:
                config['SSID'] = ssid
                dirty = True
            else:
                errors = True
                problems.append('ssid')
        secret = args.get('secret')
        if secret is not None and len(secret) > 0:
            if 8 <= len(secret) < 32:
                config['secret'] = secret
                dirty = True
            else:
                errors = True
                problems.append('secret')
        hostname = args.get('hostname')
        if hostname is not None:
            if 0 < len(hostname) < 64:
                config['hostname'] = hostname
                dirty = True
            else:
                errors = True
                problems.append('hostname')
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
            switch_host = switch_ip.encode()
            config['switch_ip'] = switch_ip
            dirty = True
        cfg_radio_number = args.get('radio_number')
        if cfg_radio_number is not None:
            cfg_radio_number = safe_int(cfg_radio_number, -1)
            if 1 <= cfg_radio_number <= 2:
                radio_number = cfg_radio_number
                config['radio_number'] = cfg_radio_number
                dirty = True
            else:
                errors = True
        poll_delay = safe_int(args.get('poll_delay'), -1)
        if poll_delay > 0:
            if 0 <= poll_delay < 60:
                switch_poll_delay = poll_delay
                config['poll_delay'] = poll_delay
                dirty = True
            else:
                errors = True
        if not errors:
            if dirty:
                save_config(config)
            response = b'ok\r\n'
            http_status = HTTP_STATUS_OK
            bytes_sent = await http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
            await msgq.put((_MSG_CONFIG_CHANGE, 0))
        else:
            response = b'parameter out of range\r\n'
            logging.error(f'problems {problems}', 'main:api_config_callback')
            http_status = HTTP_STATUS_BAD_REQUEST
            bytes_sent = await http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    else:
        response = b'GET or PUT only.'
        http_status = HTTP_STATUS_BAD_REQUEST
        bytes_sent = await http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


# noinspection PyUnusedLocal
async def api_restart_callback(http, verb, args, reader, writer, request_headers=None):
    global keep_running
    if upython:
        keep_running = False
        response = b'ok\r\n'
        http_status = HTTP_STATUS_OK
        bytes_sent = await http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    else:
        http_status = HTTP_STATUS_BAD_REQUEST
        response = b'not permitted except on PICO-W'
        bytes_sent = await http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


async def api_status_callback(http, verb, args, reader, writer, request_headers=None):  # '/api/status'
    """
    wants to have message looking like this:

    {
        "switch_connected": true,
        "lcd_lines": [
            "Elecraft K3 No Power",
            "    6 Meter Yagi    "
        ],
        "radio_power": false
    }

    """
    if False:  # this is not a noticeable improvement to using the dict.
        response = b'{"switch_connected": %s, "lcd_lines": ["%s","%s"],"radio_power": %s}' % (
            b'true' if switch_connected else b'false', lcd[0], lcd[1], b'true' if radio_power else b'false')
    else:
        response = {'lcd_lines': [lcd[0], lcd[1]],
                    'radio_power': radio_power,
                    'switch_connected': switch_connected,
                    }
    http_status = HTTP_STATUS_OK
    bytes_sent = await http.send_simple_response(writer, http_status, http.CT_APP_JSON, response)
    return bytes_sent, http_status


async def api_power_on_radio_callback(http, verb, args, reader, writer, request_headers=None):
    await power_on()
    # send the status response message
    response = {'lcd_lines': [lcd[0], lcd[1]],
                'radio_power': radio_power,
                'switch_connected': switch_connected,
                }
    http_status = HTTP_STATUS_OK
    bytes_sent = await http.send_simple_response(writer, http_status, http.CT_APP_JSON, response)
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
    red_led.value(inhibit)


async def power_on():
    poweron_pin.on()
    await asyncio.sleep(0.1)
    poweron_pin.off()
    await asyncio.sleep(0.5)


async def new_band(new_band_number):
    global band_antennae, current_antenna_list_index
    if new_band_number == 0:
        logging.warning('new band with invalid band number')
        return
    logging.info(f'new band: {BANDS[new_band_number]}', 'main:new_band')
    await update_radio_display(f'{radio_name} {BANDS[new_band_number]}', None)
    set_inhibit(1)
    band_antennae = find_band_antennae(new_band_number)
    if len(band_antennae) == 0:
        current_antenna_list_index = -1
        logging.warning(f'no antenna available for band {BANDS[new_band_number]}', 'main:new_band')
        #                                           '12345678901234567890'
        await update_radio_display(None, '*No Antenna for Band')
    else:
        if switch_connected:
            logging.info(f'new band: {BANDS[new_band_number]} got band_antennae {band_antennae}', 'main:new_band')
            await update_radio_display(None, 'Requesting Antenna')
            current_antenna_list_index = 0
            await call_select_antenna_api(band_antennae[current_antenna_list_index] + 1,
                                          (_MSG_ANTENNA_RESPONSE, (0, '')), msgq)
        else:
            logging.warning('band changed but switch is not connected', 'main:new_band')
            # do not need to update 'radio' display, it should already indicate that the switch is not connected.


async def change_band_antenna(up=True):
    global current_antenna_list_index
    logging.info(f'change_band_antenna(up={up})', 'main:change_band_antenna')
    if len(band_antennae) <= 1:
        return False
    if up:
        current_antenna_list_index += 1
        if current_antenna_list_index >= len(band_antennae):
            current_antenna_list_index = 0
    else:  # down, yeah
        current_antenna_list_index -= 1
        if current_antenna_list_index < 0:
            current_antenna_list_index = len(band_antennae) - 1
    await call_select_antenna_api(band_antennae[current_antenna_list_index] + 1, (_MSG_ANTENNA_RESPONSE, (0, '')), msgq)
    return True


# could maybe make next two funcs into their own class, encapsulate the global data... TODO
async def update_radio_display(line1=None, line2=None):
    global radio_status
    updated = False
    if line1 is not None and radio_status[0] != line1:
        radio_status[0] = line1
        updated = True
    if line2 is not None and radio_status[1] != line2:
        radio_status[1] = line2
        updated = True
    if updated:
        await show_radio_display()


async def show_radio_display():
    await msgq.put((_MSG_LCD_LINE0, radio_status[0]))  # update display
    await msgq.put((_MSG_LCD_LINE1, radio_status[1]))  # update display


async def update_network_display(line1=None, line2=None):
    global network_status
    updated = False
    if line1 is not None and line1 != network_status[0]:
        network_status[0] = line1
        updated = True
    if line2 is not None and line2 != network_status[1]:
        network_status[1] = line2
        updated = True
    if updated:
        await show_network_display()


async def show_network_display():
    await msgq.put((_MSG_LCD_LINE0, network_status[0]))  # update display
    await msgq.put((_MSG_LCD_LINE1, network_status[1]))  # update display


async def show_edit_display(menu_number, item_number):
    current_menu = MENUS[menu_number]
    menu_name = current_menu[0]
    item_value = current_menu[1][item_number]

    if menu_state == _MENU_MODE_STATE:
        menu_name = f'>{menu_name:^18s}<'

    if menu_state == _MENU_EDIT_STATE:
        item_value = f'>{item_value:^18s}<'

    await msgq.put((_MSG_LCD_LINE0, menu_name))  # update display with menu name
    await msgq.put((_MSG_LCD_LINE1, item_value))  # update display with menu item name


async def msg_loop(q):
    global antenna_bands, antenna_names, band_antennae, \
        current_antenna, current_antenna_list_index, current_antenna_name, current_band_number, \
        menu_state, network_connected, radio_name, radio_power, \
        switch_connected, switch_timeouts

    menu_number = 0
    item_number = 0

    while True:
        msg = await q.get()
        t0 = milliseconds()
        m0 = msg[0]
        m1 = msg[1]
        if logging.should_log(logging.DEBUG):
            logging.debug(f'msg received: {m0} : {m1}', 'main:msg_loop')
        if m0 == 0:
            logging.error(f'impossible message 0')
        elif m0 == _MSG_BTN_1:  # MENU button
            if m1 == 0:  # short press
                if menu_state == _RADIO_STATUS_STATE:
                    menu_state = _MENU_MODE_STATE
                    await show_edit_display(menu_number, item_number)
                else:  # any other state, return to RADIO_STATUS_STATE
                    menu_state = _RADIO_STATUS_STATE
                    await show_radio_display()
        elif m0 == _MSG_BTN_2:  # EDIT button
            if m1 == 0:  # short press
                if menu_state == _RADIO_STATUS_STATE:
                    menu_state = _NETWORK_STATUS_STATE
                    await show_network_display()
                elif menu_state == _MENU_MODE_STATE:  # in EDIT mode
                    menu_state = _MENU_EDIT_STATE
                    await show_edit_display(menu_number, item_number)
                elif menu_state == _MENU_EDIT_STATE:  # in EDIT mode, editing
                    # this is when a change actually happened.
                    # logging.info(f'edited data, menu={menu_number}, item selected = {item_number}')
                    # this should be bound to the MENUS data, not hardcoded literals 0|1...
                    #if menu_number == 0:
                    #    select_network_mode(item_number)
                    #elif menu_number == 1:
                    #    select_restart_mode(item_number)
                    ## switch out of edit value mode
                    menu_state = _MENU_MODE_STATE
                    await show_edit_display(menu_number, item_number)
        elif m0 == _MSG_BTN_3:  # UP button
            if m1 == 0:  # short press
                if menu_state == _RADIO_STATUS_STATE:
                    # next antenna for this band.
                    await change_band_antenna(up=True)
                elif menu_state == _MENU_MODE_STATE:
                    menu_number += 1
                    if menu_number >= len(MENUS):
                        menu_number = 0
                    await show_edit_display(menu_number, item_number)
                elif menu_state == _MENU_EDIT_STATE:  # in EDIT mode, editing
                    logging.info(f'UP button in edit edit mode. {menu_number} {item_number}')
                    logging.info(f'menu_state = {menu_state}')
                    logging.info(f'menu: {MENUS[menu_number]}')
                    item_number += 1
                    if item_number >= len(MENUS[menu_number][1]):
                        item_number = 0
                    await show_edit_display(menu_number, item_number)
        elif m0 == _MSG_BTN_4:  # DOWN button
            if m1 == 0:  # short press
                if menu_state == _RADIO_STATUS_STATE:
                    # previous antenna for this band.
                    await change_band_antenna(up=False)
                elif menu_state == _MENU_MODE_STATE:
                    menu_number -= 1
                    if menu_number < 0:
                        menu_number = len(MENUS) - 1
                    await show_edit_display(menu_number, item_number)
                elif menu_state == _MENU_EDIT_STATE:  # in EDIT mode, editing
                    item_number -= 1
                    if item_number < 0:
                        item_number = len(MENUS[menu_number][1]) - 1
                    await show_edit_display(menu_number, item_number)
        elif m0 == _MSG_POWER_SENSE:  # power sense changed
            if m1 == 0:
                # detect missing radio.  do something about it.
                radio_power = True
                logging.info('radio power is on', 'main:msg_loop')
            else:
                radio_power = False
                logging.info('radio power is off', 'main:msg_loop')
                await update_radio_display(f'{radio_name} No Power', None)
        elif m0 == _MSG_NETWORK_UPDOWN:
            # network up/down
            if logging.should_log(logging.DEBUG):
                logging.debug(f'msg received: {msg}', 'main:msg_loop:MSG_NETWORK_UPDOWN')
            if m1 == 1:  # network is up!
                logging.info('Network is up!', 'main:msg_loop')
                network_connected = True
                await call_status_api(0, (_MSG_STATUS_RESPONSE, None), msgq)
            else:
                logging.info('Network is DOWN!', 'main:msg_loop')
                network_connected = False
        elif m0 == _MSG_CONFIG_CHANGE:
            await call_status_api(0, (_MSG_STATUS_RESPONSE, None), msgq)
        elif m0 == _MSG_LCD_LINE0:  # LCD line 1
            lcd[0] = f'{m1:^20s}'
            # await asyncio.sleep_ms(50)
            logging.info(f'LCD0: "{lcd[0]}"', 'main:msg_loop')
        elif m0 == _MSG_LCD_LINE1:  # LCD line 2
            lcd[1] = f'{m1:^20s}'
            # await asyncio.sleep_ms(50)
            logging.info(f'LCD1: "{lcd[1]}"', 'main:msg_loop')
        elif m0 == _MSG_BAND_CHANGE:  # band change detected
            logging.info(f'band change, power = {radio_power}, m1={m1}', 'main:msg_loop')
            if not radio_power:
                await update_radio_display(f'{radio_name} No Power', None)
                set_inhibit(1)
            else:
                if 0 <= m1 < len(ELECRAFT_BAND_MAP):
                    current_band_number = ELECRAFT_BAND_MAP[m1]
                    if len(antenna_names) > 0:  # only change bands if there are antennas.
                        await new_band(current_band_number)
                    else:  # update the display with the band name
                        await update_radio_display(f'{radio_name} {BANDS[current_band_number]}', None)
                else:
                    msg = f'unknown band # {m1}'
                    logging.error(msg)
                    await update_radio_display(msg, None)
                    set_inhibit(1)
        elif m0 == _MSG_STATUS_RESPONSE:  # http status response
            http_status = m1[0]
            if http_status == HTTP_STATUS_OK:
                try:
                    status_dict = json.loads(m1[1])
                except Exception as jde:
                    switch_connected = False
                    logging.exception('cannot decode json', 'main:msg_loop', jde)
                    current_antenna = 'json decode problem'
                else:
                    switch_timeouts = 0
                    if not switch_connected:
                        logging.warning('switch_connected False to True transition', 'main:msg_loop')
                    switch_connected = True
                    status_radio_number = status_dict.get('radio_number', -1)
                    if status_radio_number == radio_number:
                        current_antenna = status_dict.get('antenna_index', -1)
                        current_antenna_name = status_dict.get('antenna_name', 'unknown antenna')
                        radio_name = status_dict.get('radio_name', 'unknown radio')
                    elif status_radio_number == -1:
                        antenna_names = status_dict.get('antenna_names', ['', '', '', '', '', '', '', ''])
                        antenna_bands = status_dict.get('antenna_bands', [0, 0, 0, 0, 0, 0, 0, 0])
                        radio_names = status_dict.get('radio_names', ['unknown radio', 'unknown radio'])
                        if radio_number == 1 or radio_number == 2:
                            radio_name = radio_names[radio_number - 1]
                        else:
                            radio_name = f'unknown radio {radio_number}'
                        current_antenna = -1
                        if radio_number == 1:
                            current_antenna = status_dict.get('radio_1_antenna', -1)
                        elif radio_number == 2:
                            current_antenna = status_dict.get('radio_2_antenna', -1)
                        if current_antenna == 0:
                            current_antenna_name = "Antenna DISCONNECTED"
                        elif 1 <= current_antenna <= 8:
                            current_antenna_name = antenna_names[current_antenna - 1]
                        else:
                            current_antenna_name = f'unknown antenna {current_antenna}'
                    else:
                        logging.warning(f'weird status_radio_number {status_radio_number}',
                                        'main:msg_loop:_MSG_STATUS_RESPONSE')
            elif http_status == _API_STATUS_TIMEOUT:
                switch_timeouts += 1
                if logging.should_log(logging.DEBUG):
                    logging.debug(f'switch timeouts={switch_timeouts}', 'main:msg_loop:MSG_STATUS_RESPONSE')

                if switch_timeouts == 2:
                    switch_connected = False
                    current_antenna = -1
                    current_antenna_name = 'No Antenna Switch!'
                # TODO try the status read again?
                if False:
                    if switch_poll_delay > 2 and network_connected:
                        await asyncio.sleep(1)
                        await call_status_api(0, (_MSG_STATUS_RESPONSE, None), msgq)
            else:
                logging.warning(f'API call returned HTTP status {http_status} {m1}', 'main:msg_loop')

            await update_radio_display(None, current_antenna_name)

            if not radio_power:
                msg = f'{radio_name} No Power'
                # if logging.should_log(logging.DEBUG):  # doesn't matter
                logging.debug(msg, 'main:msg_loop:NoPower')
                await update_radio_display(msg, None)
                set_inhibit(1)
            else:
                if current_band_number < 1 or current_band_number > 13:
                    # this does not look like a valid band choice, read the band data again.
                    band_detector.invalidate()
                else:
                    msg = f'{radio_name} {BANDS[current_band_number]}'
                    await update_radio_display(msg, None)
                    if current_antenna < 1:
                        set_inhibit(1)
                    else:
                        if MASKS[current_band_number] & antenna_bands[current_antenna - 1]:
                            set_inhibit(0)
                            await update_radio_display(None, current_antenna_name)
                        else:
                            set_inhibit(1)
                            # try to get the right band...
                            await new_band(current_band_number)
        elif m0 == _MSG_ANTENNA_RESPONSE:  # http select antenna response
            # print(f'm1={m1}')  # FIXME
            http_status = m1[0]
            payload = m1[1].decode().strip()
            if http_status == 0:  # api call failed
                switch_connected = False
                current_antenna = -1
                current_antenna_name = '_No Antenna Switch!_'
                #                      '12345678901234567890'
                await update_radio_display(None, current_antenna_name)
            elif http_status == HTTP_STATUS_OK:
                await call_status_api(0, (_MSG_STATUS_RESPONSE, None), msgq)
            elif HTTP_STATUS_BAD_REQUEST <= http_status <= 499:
                if len(band_antennae) == 0 or current_antenna_list_index == len(band_antennae) - 1:
                    logging.warning(f'no antenna available for band ')
                    await update_radio_display(None, f'*{payload}')
                    set_inhibit(1)
                else:
                    # if there is another antenna candidate, try to get it
                    logging.info(f'API call returned HTTP status {http_status} {m1}',
                                 'main:msg_loop:MSG_ANTENNA_RESPONSE')
                    await update_radio_display(None, '')
                    if current_antenna_list_index < len(band_antennae) - 1:
                        current_antenna_list_index = current_antenna_list_index + 1
                    await call_select_antenna_api(band_antennae[current_antenna_list_index] + 1,
                                                  (_MSG_ANTENNA_RESPONSE, (0, '')), msgq)
            else:  # some other HTTP/status code...
                logging.warning(f'select antenna API call returned status {http_status} {m1}', 'main:msg_loop')
        else:
            logging.error(f'unhandled message ({m0}, {m1})', 'main:msg_loop')
        dt = milliseconds() - t0
        if dt > 100:
            logging.warning(f'Message {m0} handling took {dt} ms.', 'main:msg_loop')
        elif logging.should_log(logging.DEBUG):
            logging.debug(f'Message {m0} handling took {dt} ms.', 'main:msg_loop')


async def net_msg_func(message: str, msg_status=0) -> None:
    global network_status
    if logging.should_log(logging.INFO):
        logging.info(f'network message: "{message.strip()}", {msg_status}', 'main:net_msg_func')
    lines = message.split('\n')
    if len(lines) == 1:
        await update_network_display(message)
    else:
        await update_network_display(lines[0], lines[1])
    if msg_status == 1:
        await msgq.put((_MSG_NETWORK_UPDOWN, 1))


async def poll_switch():
    while True:
        if network_connected:
            await call_status_api(radio_number, (_MSG_STATUS_RESPONSE, None), msgq)
        if switch_poll_delay > 0:
            await asyncio.sleep(switch_poll_delay)


async def main():
    global keep_running, config, restart, radio_number, switch_host, switch_poll_delay
    config = read_config()
    if len(config) == 0:
        # create default configuration
        config = default_config()
        config['ap_mode'] = sw1.value() == 0
        save_config(config)
    else:
        config['ap_mode'] = sw1.value() == 0

    config_level = config.get('log_level')
    if config_level:
        logging.set_level(config_level)

    radio_number = config.get('radio_number', -1)
    switch_host = config.get('switch_ip', 'localhost').encode()
    switch_poll_delay = safe_int(config.get('poll_delay') or 10, 10)

    web_port = safe_int(config.get('web_port') or DEFAULT_WEB_PORT, DEFAULT_WEB_PORT)
    if web_port < 0 or web_port > 65535:
        web_port = DEFAULT_WEB_PORT

    time_set = False

    if upython:
        # if logging.loglevel != logging.DEBUG:
        #    _ = Watchdog()
        picow_network = PicowNetwork(config, DEFAULT_SSID, DEFAULT_SECRET, net_msg_func, long_messages=True)
        _msg_loop_task = asyncio.create_task(msg_loop(msgq))
        _switch_poller_task = asyncio.create_task(poll_switch())
    else:
        picow_network = None
        _msg_loop_task = None
        _switch_poller_task = None

    http_server = HttpServer(content_dir=CONTENT_DIR)
    http_server.add_uri_callback(b'/', slash_callback)
    http_server.add_uri_callback(b'/api/config', api_config_callback)
    http_server.add_uri_callback(b'/api/get_files', api_get_files_callback)
    http_server.add_uri_callback(b'/api/upload_file', api_upload_file_callback)
    http_server.add_uri_callback(b'/api/remove_file', api_remove_file_callback)
    http_server.add_uri_callback(b'/api/rename_file', api_rename_file_callback)
    http_server.add_uri_callback(b'/api/restart', api_restart_callback)
    http_server.add_uri_callback(b'/api/status', api_status_callback)
    http_server.add_uri_callback(b'/api/power_on_radio', api_power_on_radio_callback)

    logging.info(f'Starting web service on port {web_port}', 'main:main')
    _web_server_task = asyncio.create_task(asyncio.start_server(http_server.serve_http_client, '0.0.0.0', web_port))

    while keep_running:
        await asyncio.sleep(1.0)
        if picow_network is not None and picow_network.is_connected() and not time_set:
            get_ntp_time()
            if time.time() > 1700000000:
                time_set = True

    if upython:
        logging.warning('calling soft_reset', 'main:main')
        machine.soft_reset()


if __name__ == '__main__':
    reset_cause = machine.reset_cause()
    logging.loglevel = logging.INFO
    logging.info(f'starting, reset_cause={reset_cause}', 'main:__main__')
    logging.info(f'BandSelector version {__version__} running on {sys.implementation[2]}', 'main:__main__')
    machine.freq(200000000)  # overclock to 200 Mhz, is now supported, stock pico 2 is 150 MHz, pico is 133 MHz.
    logging.info(f'clock set to {machine.freq()} hz')
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info('KeyboardInterrupt -- bye bye', 'main:__main__')
    finally:
        asyncio.new_event_loop()
    logging.info('done', 'main:__main__')
