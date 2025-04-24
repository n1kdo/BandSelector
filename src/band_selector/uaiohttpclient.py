import asyncio

class ClientResponse:
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer
        self.headers = []
        self.status = 0

    async def read(self, sz:int=-1) -> bytes:
        data = await self.reader.read(sz)
        # self.writer.close()  # does nothing
        await self.writer.wait_closed()
        # self.reader.close()  # does nothing
        await self.reader.wait_closed()
        return data

    def __repr__(self) -> str:
        return '<ClientResponse %d %s>' % (self.status, self.headers)


class ChunkedClientResponse(ClientResponse):
    def __init__(self, reader, writer):
        super().__init__(reader, writer)
        self.chunk_size = 0

    async def read(self, sz:int=4 * 1024 * 1024) -> bytes:
        if self.chunk_size == 0:
            line = await self.reader.readline()
            # print('chunk line:', l)
            line = line.split(b';', 1)[0]
            self.chunk_size = int(line, 16)
            # print('chunk size:', self.chunk_size)
            if self.chunk_size == 0:
                # End of message
                sep = await self.reader.read(2)
                assert sep == b'\r\n'
                # self.writer.close()  # does nothing in micropython
                await self.writer.wait_closed()
                # self.reader.close()
                await self.reader.wait_closed()
                return b''
        data = await self.reader.read(min(sz, self.chunk_size))
        self.chunk_size -= len(data)
        if self.chunk_size == 0:
            sep = await self.reader.read(2)
            assert sep == b'\r\n'
        # self.writer.close()  # does nothing!
        # see https://github.com/micropython/micropython/blob/master/extmod/asyncio/stream.py#L16
        await self.writer.wait_closed()
        # self.reader.close()  # does nothing
        await self.reader.wait_closed()
        return data

    def __repr__(self) -> str:
        return '<ChunkedClientResponse %d %s>' % (self.status, self.headers)


async def request_raw(method:bytes, url:bytes) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    try:
        proto, dummy, host, path = url.split(b'/', 3)
    except ValueError:
        proto, dummy, host = url.split(b'/', 2)
        path = ''

    if b':' in host:
        host, port = host.split(b':')
        port = int(port)
    else:
        port = 80

    if proto != b'http:':
        raise ValueError(f'Unsupported protocol: {proto}')
    reader, writer = await asyncio.open_connection(host, port)
    # Use protocol 1.0, because 1.1 always allows to use chunked
    # transfer-encoding But explicitly set Connection: close, even
    # though this should be default for 1.0, because some servers
    # misbehave w/o it.
    query = b'%s /%s HTTP/1.0\r\nHost: %s\r\nConnection: close\r\nUser-Agent: compat\r\n\r\n' % (
        method,
        path,
        host,
    )
    # awrite is supported but apparently undocumented in micropython asyncio
    # can use write and then drain -- does the same thing effectively
    writer.write(query)
    await writer.drain()
    return reader, writer


async def request(method:bytes, url:bytes):
    redir_cnt = 0
    chunked = False
    status = 0
    headers = []
    while redir_cnt < 2:
        reader, writer = await request_raw(method, url)
        headers = []
        # readline is a co-routine in micropython, safe to ignore warning.
        sline = await reader.readline()
        sline = sline.split(None, 2)
        status = int(sline[1])
        chunked = False
        while True:
            line = await reader.readline()
            if not line or line == b'\r\n':
                break
            headers.append(line)
            if line.startswith(b'Transfer-Encoding:'):
                if b'chunked' in line:
                    chunked = True
            elif line.startswith(b'Location:'):
                url = line.rstrip().split(None, 1)[1].decode('latin-1')

        if 301 <= status <= 303:
            redir_cnt += 1
            # aclose() is aliased to wait_closed()
            await reader.wait_closed()
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
