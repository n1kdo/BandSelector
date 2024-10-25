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

class FourBits:
    debounce_ms = 50

    def __init__(self, pins, queue, base_msg):
        """
        this thing looks at a collection of pins and returns an integer value.
        use case is to read band data from Elecraft K3/K4 accessory jack.
        :param pins: is a list or tuple [MSB...LSB] (lsb higher index)
        :param queue: the message queue to write events to
        :param base_msg: this is a tuple. this class will write the numeric value of the pins to the 2nd element.
        """
        self._pins = []
        for pin in pins:
            if isinstance(pin, int):
                pin = Pin(pin, mode=Pin.IN, pull=Pin.PULL_UP)
            self._pins.append(pin)
        self._queue = queue
        self._base_msg = base_msg
        self._last = None # always send an event after init.
        asyncio.create_task(self._bits_checker())

    def invalidate(self):
        self._last = None

    async def _bits_checker(self):
        while True:
            latest = 0
            for pin in self._pins:
                latest = (latest << 1) + pin.value()
            if latest != self._last:
                self._last = latest
                new_msg = (self._base_msg[0], latest)
                await self._queue.put(new_msg)
            await asyncio.sleep_ms(FourBits.debounce_ms)
