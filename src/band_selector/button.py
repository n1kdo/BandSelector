__author__ = 'J. B. Otterson'
__copyright__ = 'Copyright 2024, 2025 J. B. Otterson N1KDO.'
__version__ = '0.1.4'

#
# Copyright 2024, 2025, J. B. Otterson N1KDO.
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

from asyncio import (create_task, sleep_ms)
from machine import Pin
import micropython

class Button:
    __slots__ = ('_pin', '_queue', '_short_msg', '_long_msg', '_last', '_timer')
    _debounce_ms = 50
    _long_press_count = 10

    def __init__(self, pin, queue, short_press_message, long_press_message):
        if isinstance(pin, int):
            pin = Pin(pin, mode=Pin.IN, pull=Pin.PULL_UP)
        self._pin = pin
        self._queue = queue
        self._short_msg = short_press_message
        self._long_msg = long_press_message
        self._last = self._pin.value()  # or 1
        self._timer = 0
        create_task(self._edge_checker())

    @micropython.native
    async def _edge_checker(self):
        while True: # runs forever -- must await
            latest = self._pin.value()
            if latest != self._last:  # is it different from the last time?
                if latest == 1:  # button was released
                    await self._queue.put(self._long_msg if self._timer >= Button._long_press_count else self._short_msg)
                 # and reset
                self._last = latest
                self._timer = 0
            else:  # it is the same value as last time.
                self._timer += 1
            await sleep_ms(self._debounce_ms)

    def invalidate(self):
        self._last = None
        self._timer = 0
