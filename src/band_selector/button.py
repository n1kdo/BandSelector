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
