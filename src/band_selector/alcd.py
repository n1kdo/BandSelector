# LCD class for Micropython and uasyncio.
#
__author__ = 'J. B. Otterson'
__copyright__ = 'Copyright 2024, 2025 J. B. Otterson N1KDO.'
__version__ = '0.1.2'
#
# bastardized from Peter Hinch's alcd.py retrieved from
#  https://github.com/peterhinch/micropython-async/blob/master/v3/as_drivers/hd44780/alcd.py
#
# LCD class for Micropython and uasyncio.
# Author: Peter Hinch
# Copyright Peter Hinch 2017 Released under the MIT license
# V1.1 24 Apr 2020 Updated for uasyncio V3
# V1.0 13 May 2017

# Assumes an LCD with standard Hitachi HD44780 controller chip wired using four data lines
# Code has only been tested on two line LCD displays.

# My code is based on this program written for the Raspberry Pi
# http://www.raspberrypi-spy.co.uk/2012/07/16x2-lcd-module-control-using-python/
# HD44780 LCD Test Script for
# Raspberry Pi
#
# Author : Matt Hawkins
# Site   : http://www.raspberrypi-spy.co.uk

import asyncio

# noinspection PyUnresolvedReferences
from time import (sleep_ms, sleep_us)

# noinspection PyUnresolvedReferences
from machine import Pin


# ********************************** GLOBAL CONSTANTS: TARGET BOARD PIN NUMBERS *************************************

# Supply board pin numbers as a tuple in order Rs, E, D4, D5, D6, D7

PINLIST = ("Y1", "Y2", "Y6", "Y5", "Y4", "Y3")  # As used in testing.

# **************************************************** LCD CLASS ****************************************************
# Initstring:
# 0x33, 0x32: See flowchart P24 send 3,3,3,2
# 0x28: Function set DL = 1 (4 bit) N = 1 (2 lines) F = 0 (5*8 bit font)
# 0x0C: Display on/off: D = 1 display on C, B = 0 cursor off, blink off
# 0x06: Entry mode set: ID = 1 increment S = 0 display shift??
# 0x01: Clear display, set DDRAM address = 0
# Original code had timing delays of 50uS. Testing with the Pi indicates that time.sleep() can't issue delays shorter
# than about 250uS. There also seems to be an error in the original code in that the datasheet specifies a delay of
# >4.1mS after the first 3 is sent. To simplify I've imposed a delay of 5mS after each initialisation pulse: the time to
# initialise is hardly critical. The original code worked, but I'm happier with something that complies with the spec.

# Async version:
# No point in having a message queue: people's eyes aren't that quick. Just display the most recent data for each line.
# Assigning changed data to the LCD object sets a "dirty" flag for that line. The LCD's runlcd thread then updates the
# hardware and clears the flag

# lcd_byte and lcd_nybble method use explicit delays. This is because execution
# time is short relative to general latency (on the order of 300μs).


class LCD:  # LCD objects appear as read/write lists
    __slots__ = ('_LCD_E', '_LCD_RS', '_datapins', '_cols', '_rows', '_lines', '_dirty', '_initialising')

    INITSTRING = b"\x33\x32\x28\x0C\x06\x01"
    LCD_LINES = (0x80, 0xC0)  # LCD RAM address for the 1st and 2nd line (0 and 40H)
    CHR = True
    CMD = False
    E_PULSE = const(50)  # Timing constants in uS
    E_DELAY = const(50)

    def __init__(self, pinlist, cols, rows=2):  # Init with pin nos for enable, rs, D4, D5, D6, D7
        self._initialising = True
        self._LCD_E = Pin(pinlist[1], Pin.OUT)  # Create and initialise the hardware pins
        self._LCD_RS = Pin(pinlist[0], Pin.OUT)
        self._datapins = [Pin(pin_name, Pin.OUT) for pin_name in pinlist[2:]]
        self._cols = cols
        self._rows = rows
        self._lines = [""] * self._rows
        self._dirty = [False] * self._rows
        for b in LCD.INITSTRING:
            self.lcd_byte(b, LCD.CMD)
            self._initialising = False  # Long delay after first byte only
        asyncio.create_task(self.update_lcd())

    def lcd_nybble(self, bits):  # send the LS 4 bits
        for pin in self._datapins:
            pin.value(bits & 0x01)
            bits >>= 1
        sleep_us(LCD.E_DELAY)  # 50μs
        self._LCD_E.value(True)  # Toggle the enable pin
        sleep_us(LCD.E_PULSE)
        self._LCD_E.value(False)
        if self._initialising:
            sleep_ms(5)
        else:
            sleep_us(LCD.E_DELAY)  # 50μs

    def lcd_byte(self, bits, mode):  # Send byte to data pins: bits = data
        self._LCD_RS.value(mode)  # mode = True  for character, False for command
        self.lcd_nybble(bits >> 4)  # send high bits
        self.lcd_nybble(bits)  # then low ones

    def __setitem__(self, line, message):  # Send string to display line 0 or 1
        message = "{0:{1}.{1}}".format(message, self._cols)
        if message != self._lines[line]:  # Only update LCD if data has changed
            self._lines[line] = message  # Update stored line
            self._dirty[line] = True  # Flag its non-correspondence with the LCD device

    def __getitem__(self, line):
        return self._lines[line]

    async def update_lcd(self):
        asleep_ms = asyncio.sleep_ms
        # Periodically check for changed text and update LCD if so
        while True:
            for row in range(self._rows):
                if self._dirty[row]:
                    msg = self[row]
                    self._dirty[row] = False
                    self.lcd_byte(LCD.LCD_LINES[row], LCD.CMD)
                    for thisbyte in msg:
                        self.lcd_byte(ord(thisbyte), LCD.CHR)
                        await asleep_ms(0)  # Reschedule ASAP
            await asleep_ms(20)  # Give other coros a look-in
