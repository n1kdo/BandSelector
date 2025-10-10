__author__ = 'J. B. Otterson'
__copyright__ = 'Copyright 2024, 2025 J. B. Otterson N1KDO.'
__version__ = '0.1.2'

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


class GPIO_Pin:
    __slots__ = ('_pin', '_queue', '_low_msg', '_hi_msg', '_last')
    debounce_ms = 50

    def __init__(self, pin, queue, low_msg, hi_msg):
        if isinstance(pin, int):
            pin = Pin(pin, mode=Pin.IN, pull=Pin.PULL_UP)
        self._pin = pin
        self._queue = queue
        self._low_msg = low_msg
        self._hi_msg = hi_msg
        self._last = None # always send an event after init.
        create_task(self._edge_checker())

    @micropython.native
    async def _edge_checker(self):
        pin_value = self._pin.value  # Cache method lookup
        queue_put = self._queue.put

        while True:
            latest = pin_value()
            if latest != self._last:  # is it different than the last time?
                # yeah, send a message
                await queue_put(self._hi_msg if latest else self._low_msg)
                 # and reset
                self._last = latest
            await sleep_ms(GPIO_Pin.debounce_ms)

    def invalidate(self):
        self._last = None
