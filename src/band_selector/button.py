#
# Copyright 2024, J. B. Otterson N1KDO.
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
from machine import Pin

class Button:
    debounce_ms = 50

    def __init__(self, pin, queue, low_msg, hi_msg):
        if isinstance(pin, int):
            pin = Pin(pin, mode=Pin.IN, pull=Pin.PULL_UP)
        self._pin = pin
        self._queue = queue
        self._low_msg = low_msg
        self._hi_msg = hi_msg
        self._last = None # always send an event after init.
        asyncio.create_task(self._edge_checker())

    async def _edge_checker(self):
        while True:
            latest = self._pin.value()
            if latest != self._last:
                self._last = latest
                await self._queue.put(self._hi_msg if latest else self._low_msg)
            await asyncio.sleep_ms(Button.debounce_ms)

    def invalidate(self):
        self._last = None
