#
# this is a bastardized version of the uaiohttpclient from
# https://github.com/micropython/micropython-lib/tree/master/micropython/uaiohttpclient
#
# The original code was licensed under the MIT license, so this code remains so.
#
# some of the modifications are:
#  * converted strings to bytes
#  * added type hints
#  * make sure that the socket is closed
#  * every blocking read has a deadline (timeout) so a stalled server cannot
#    hang a task forever, and the socket is released explicitly on every
#    failure path (timeout, error, cancellation) instead of waiting for GC.
#  * chunked-encoding chunk sizes are capped so a hostile/buggy server cannot
#    force an unbounded heap allocation.
#
__author__ = 'J. B. Otterson'
__copyright__ = """
The MIT License (MIT)

Copyright (c) 2013, 2014 micropython-lib contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""
__version__ = '0.1.4'  # 2026-09-13

import asyncio
import errno
import socket

from utils import upython

# default deadline (seconds) for each blocking read on a response stream.
_READ_TIMEOUT = 5.0

# cap on the number of bytes read for a single chunked-encoding chunk, so a
# hostile/buggy server cannot declare a multi-MB chunk and force an unbounded
# heap allocation on the Pico-W's ~264 KB of RAM.
_MAX_CHUNK_SIZE = 65536

# cap on the number of response header lines accepted before the response is
# rejected, so a hostile/buggy server cannot exhaust the heap with endless
# headers. resp.headers is only used for __repr__, so truncation is safe.
_MAX_HEADER_LINES = 64


class ClientResponse:
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer
        self.headers = []
        self.status = 0

    async def _close(self):
        # micropython: close() is a no-op; wait_closed() is what actually
        # closes the socket (reader and writer are the same object there).
        # cpython: close() initiates the close; wait_closed() waits for it.
        self.writer.close()
        await self.writer.wait_closed()

    async def read(self, sz:int=-1, timeout:float=_READ_TIMEOUT) -> bytes:
        try:
            data = await asyncio.wait_for(self.reader.read(sz), timeout)
        except BaseException:
            # timeout, socket error, or cancellation by an outer wait_for():
            # release the socket now instead of waiting for GC.
            await self._close()
            raise
        await self._close()
        return data

    def __repr__(self) -> str:
        return f'<ClientResponse {self.status} {self.headers}'


class ChunkedClientResponse(ClientResponse):
    def __init__(self, reader, writer):
        super().__init__(reader, writer)
        self.chunk_size = 0

    async def read(self, sz:int=_MAX_CHUNK_SIZE, timeout:float=_READ_TIMEOUT) -> bytes:
        try:
            if self.chunk_size == 0:
                line = await asyncio.wait_for(self.reader.readline(), timeout)
                # print('chunk line:', l)
                line = line.split(b';', 1)[0]
                self.chunk_size = int(line, 16)
                # print('chunk size:', self.chunk_size)
                if self.chunk_size == 0:
                    # End of message
                    sep = await asyncio.wait_for(self.reader.read(2), timeout)
                    assert sep == b'\r\n'
                    await self._close()
                    return b''
            data = await asyncio.wait_for(self.reader.read(min(sz, self.chunk_size)), timeout)
            self.chunk_size -= len(data)
            if self.chunk_size == 0:
                sep = await asyncio.wait_for(self.reader.read(2), timeout)
                assert sep == b'\r\n'
        except BaseException:
            # timeout, socket error, or cancellation by an outer wait_for():
            # release the socket now instead of waiting for GC.
            await self._close()
            raise
        await self._close()
        return data

    def __repr__(self) -> str:
        return f'<ChunkedClientResponse {self.status} {self.headers}'


def _mp_open_connection(host: str, port: int):
    # MicroPython's asyncio.open_connection() creates the socket before it waits
    # for the connect to complete, and never closes it if the task is cancelled
    # or the connect fails.  MicroPython has no finalizers, so the socket (and its
    # lwIP PCB) leaks forever.  This mirrors open_connection() but closes the
    # socket on every failure path.  It is a generator-coroutine because that is
    # how MP's Stream methods suspend on IO: queue_write() registers the current
    # task with the poller as a side effect of the call.
    from asyncio import core
    from asyncio.stream import Stream

    ai = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)[0]
    s = socket.socket(ai[0], ai[1], ai[2])
    try:
        s.setblocking(False)
        try:
            s.connect(ai[-1])
        except OSError as er:
            if er.errno != errno.EINPROGRESS:
                raise
        ss = Stream(s)
        try:
            yield core._io_queue.queue_write(s)
        except BaseException:
            s.close()
            raise
        return ss, ss
    except BaseException:
        s.close()
        raise


async def request_raw(method:bytes, url:bytes) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    try:
        proto, _, host, path = url.split(b'/', 3)
    except ValueError:
        proto, _, host = url.split(b'/', 2)
        path = b''

    if b':' in host:
        host, port = host.split(b':')
        port = int(port)
    else:
        port = 80

    if proto != b'http:':
        raise ValueError(f'Unsupported protocol: {proto}')

    # cpython's open_connection() needs a str host; micropython accepts both.
    if upython:
        # MP's open_connection() leaks the socket on cancel/failure (see above).
        reader, writer = await _mp_open_connection(host.decode(), port)
    else:
        reader, writer = await asyncio.open_connection(host.decode(), port)
    # Use protocol 1.0, because 1.1 always allows to use chunked
    # transfer-encoding But explicitly set Connection: close, even
    # though this should be default for 1.0, because some servers
    # misbehave w/o it.
    try:
        writer.write(b'%s /%s HTTP/1.0\r\nHost: %s\r\nConnection: close\r\nUser-Agent: compat\r\n\r\n' % (method, path, host))
        await writer.drain()
    except BaseException:
        # Don't leak an established connection if the request line cannot be
        # sent (e.g. the task was cancelled during drain).
        writer.close()
        await writer.wait_closed()
        raise
    return reader, writer


async def request(method:bytes, url:bytes, timeout:float=_READ_TIMEOUT):
    redir_cnt = 0
    chunked = False
    status = 0
    headers = []
    while redir_cnt < 2:
        reader, writer = await request_raw(method, url)
        try:
            # readline is a co-routine in micropython, safe to ignore warning.
            sline = await asyncio.wait_for(reader.readline(), timeout)
            sline = sline.split(None, 2)
            status = int(sline[1])
            chunked = False
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout)
                if not line or line == b'\r\n':
                    break
                if len(headers) >= _MAX_HEADER_LINES:
                    raise ValueError('too many response header lines')
                headers.append(line)
                if line.startswith(b'Transfer-Encoding:') and b'chunked' in line:
                    chunked = True
                elif line.startswith(b'Location:'):
                    # keep url as bytes: request_raw() and the request line
                    # are all bytes-based (the original .decode() here made
                    # the follow-up request_raw() call fail on both runtimes).
                    url = line.rstrip().split(None, 1)[1]
        except BaseException:
            # timeout, malformed response, or cancellation by an outer
            # wait_for(): release the socket now instead of waiting for GC.
            writer.close()
            await writer.wait_closed()
            raise

        if 301 <= status <= 303:
            redir_cnt += 1
            writer.close()
            await writer.wait_closed()
            continue
        break

    if chunked:
        resp = ChunkedClientResponse(reader, writer)
    else:
        resp = ClientResponse(reader, writer)
    resp.status = status
    resp.headers = headers
    return resp
