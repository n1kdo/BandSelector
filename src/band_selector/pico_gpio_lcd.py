"""Implements a HD44780 character LCD connected via pyboard GPIO pins."""


from utils import milliseconds, upython, safe_int

if upython:
    import machine
    from time import sleep_ms, sleep_us
    import uasyncio as asyncio
else:
    import asyncio
    from not_machine import machine
    from time import sleep
    sleep_ms = lambda x: sleep(x / 1000.0)
    sleep_us = lambda x: sleep(x / 1000000.0)

from lcd_api import LcdApi

class GpioLcd(LcdApi):
    """
    Implements a HD44780 character LCD connected via raspberry pi pico GPIO pins.
    Probably works with other Micropython implementations.
    """

    def __init__(self, rs_pin, enable_pin, d0_pin=None, d1_pin=None,
                 d2_pin=None, d3_pin=None, d4_pin=None, d5_pin=None,
                 d6_pin=None, d7_pin=None, rw_pin=None, backlight_pin=None,
                 num_lines=2, num_columns=16):
        """Constructs the GpioLcd object. All the arguments must be machine.Pin
        objects which describe which pin the given line from the LCD is
        connected to.  The Pins should be configured with options and value
        machine.Pin.OUT, value=0

        When used in 4-bit mode, only D4, D5, D6, and D7 are physically
        connected to the LCD panel. This function allows you call it like
        GpioLcd(rs, enable, D4, D5, D6, D7) and it will interpret that as
        if you had actually called:
        GpioLcd(rs, enable, d4=D4, d5=D5, d6=D6, d7=D7)

        The enable 8-bit mode, you need pass d0 through d7.

        The rw pin isn't used by this library, but if you specify it, then
        it will be set low.
        """
        self.rs_pin = rs_pin
        self.enable_pin = enable_pin
        self.rw_pin = rw_pin
        self.backlight_pin = backlight_pin
        self._4bit = True
        if d4_pin and d5_pin and d6_pin and d7_pin:
            self.d0_pin = d0_pin
            self.d1_pin = d1_pin
            self.d2_pin = d2_pin
            self.d3_pin = d3_pin
            self.d4_pin = d4_pin
            self.d5_pin = d5_pin
            self.d6_pin = d6_pin
            self.d7_pin = d7_pin
            if self.d0_pin and self.d1_pin and self.d2_pin and self.d3_pin:
                self._4bit = False
        else:
            # This is really 4-bit mode, and the 4 data pins were just
            # passed as the first 4 arguments, so we switch things around.
            self.d0_pin = None
            self.d1_pin = None
            self.d2_pin = None
            self.d3_pin = None
            self.d4_pin = d0_pin
            self.d5_pin = d1_pin
            self.d6_pin = d2_pin
            self.d7_pin = d3_pin

        # See about splitting this into begin

        sleep_ms(20)   # Allow LCD time to powerup
        # Send reset 3 times
        self.hal_write_init_nibble(self.LCD_FUNCTION_RESET)
        sleep_ms(5)    # need to delay at least 4.1 msec
        self.hal_write_init_nibble(self.LCD_FUNCTION_RESET)
        sleep_ms(1)
        self.hal_write_init_nibble(self.LCD_FUNCTION_RESET)
        sleep_ms(1)
        cmd = self.LCD_FUNCTION
        if not self._4bit:
            cmd |= self.LCD_FUNCTION_8BIT
        self.hal_write_init_nibble(cmd)
        sleep_ms(1)
        LcdApi.__init__(self, num_lines, num_columns)
        if num_lines > 1:
            cmd |= self.LCD_FUNCTION_2LINES
        self.hal_write_command(cmd)

    def hal_pulse_enable(self):
        """Pulse the enable line high, and then low again."""
        self.enable_pin.low()
        sleep_us(1)
        self.enable_pin.high()
        sleep_us(1)       # Enable pulse needs to be > 450 nsec
        self.enable_pin.low()
        sleep_us(100)     # Commands need > 37us to settle

    def hal_write_init_nibble(self, nibble):
        """Writes an initialization nibble to the LCD.

        This particular function is only used during initialization.
        """
        self.hal_write_4bits(nibble >> 4)

    def hal_backlight_on(self):
        """Allows the hal layer to turn the backlight on."""
        if self.backlight_pin:
            self.backlight_pin.high()

    def hal_backlight_off(self):
        """Allows the hal layer to turn the backlight off."""
        if self.backlight_pin:
            self.backlight_pin.low()

    def hal_write_command(self, cmd):
        """Writes a command to the LCD.

        Data is latched on the falling edge of E.
        """
        self.rs_pin.low()
        self.hal_write_8bits(cmd)
        if cmd <= 3:
            # The home and clear commands require a worst
            # case delay of 4.1 msec
            sleep_ms(5)

    def hal_write_data(self, data):
        """Write data to the LCD."""
        self.rs_pin.high()
        self.hal_write_8bits(data)

    def hal_write_8bits(self, value):
        """Writes 8 bits of data to the LCD."""
        if self.rw_pin:
            self.rw_pin.low()
        if self._4bit:
            self.hal_write_4bits(value >> 4)
            self.hal_write_4bits(value)
        else:
            self.d3_pin.value(value & 0x08)
            self.d2_pin.value(value & 0x04)
            self.d1_pin.value(value & 0x02)
            self.d0_pin.value(value & 0x01)
            self.hal_write_4bits(value >> 4)

    def hal_write_4bits(self, nibble):
        """Writes 4 bits of data to the LCD."""
        self.d7_pin.value(nibble & 0x08)
        self.d6_pin.value(nibble & 0x04)
        self.d5_pin.value(nibble & 0x02)
        self.d4_pin.value(nibble & 0x01)
        self.hal_pulse_enable()
