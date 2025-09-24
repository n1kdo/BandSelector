from asyncio import create_task, sleep_ms
import micro_logging as logging

# taken from https://github.com/micropython/micropython-lib/python-stdlib/inspect/inspect.py
_g = lambda: (yield)
def iscoroutinefunction(obj):
    return isinstance(obj, type(_g))

class Timer:
    """
    Timer class contains information about Timer events.
    """
    indexCounter = -1

    def __init__(self, delay:float, callback, arg=None, auto_reset:bool=False)->None:
        Timer.indexCounter += 1
        self.index = Timer.indexCounter
        self.delay = int(delay*10)
        self.remaining = self.delay
        self.auto_reset = auto_reset
        self.callback = callback
        self.argument = arg
        self.coroutine = iscoroutinefunction(callback)


class TimerManager:
    """
    TimerManager provides one-shot or periodic timer function callbacks.
    Note that resolution is "about" 100 milliseconds.
    """

    def __init__(self):
        self._timers = {}
        self._run = True
        create_task(self._check_timers())

    def add_timer(self, delay, callback, arg, auto_reset=False)->int:
        """
        Adds a new timer .
        :param delay: how long to delay the timer.
        :param callback:  function to execute when timer expires
        :param arg: argument to pass to callback
        :param auto_reset: set True to cause timer to repeat
        :return: the timer index, used to cancel or reset the timer.
        """
        timer = Timer(delay, callback, arg, auto_reset)
        self._timers[timer.index] = timer
        #logging.info(f'added timer {timer.index} for {delay} sec...', 'timer_manager:add_timer')
        return timer.index

    def cancel_timer(self, index:int)->None:
        """
        Cancels a timer by index.
        :param index: the timer to cancel.
        :return: None
        """
        timer = self._timers.get(index)
        if timer is not None:
            del self._timers[index]

    def reset_timer(self, index:int)->None:
        """
        Resets a timer by index.
        :param index:  the timer to reset
        :return: None
        """
        #logging.info(f'timer {index} reset...', 'timer_manager:reset_timer')
        timer = self._timers.get(index)
        if timer is not None:
            timer.remaining = timer.delay

    def stop(self) -> None:
        """
        Shut down the timer processor.
        :return: None
        """
        self._run = False

    async def _check_timers(self):
        while self._run:
            delete_list = []
            for timer in self._timers.values():
                timer.remaining -= 1
                if timer.remaining == 0:
                    #logging.info(f'timer {timer.index} timed out...', 'timer_manager:_check_timers')
                    try:
                        if timer.coroutine:
                            await timer.callback(timer.argument)
                        else:
                            timer.callback(timer.argument)
                    except Exception as e:
                        print(e)
                        exit(1)
                    if timer.auto_reset:
                        timer.remaining = timer.delay
                    else:
                        delete_list.append(timer.index)
            for index in delete_list:
                del self._timers[index]
            await sleep_ms(100)
