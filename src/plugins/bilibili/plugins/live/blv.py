import json
import zlib
from asyncio import sleep
from collections.abc import AsyncGenerator
from contextlib import suppress
from struct import Struct

import brotli
import websockets
from httpx import AsyncClient

from .....utils import run_task
from ... import plugin_config as bilibili_config
from .._utils import raise_for_status

client = AsyncClient(
    headers={
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
        "origin": "https://live.bilibili.com",
        "referer": "https://live.bilibili.com/",
    },
    cookies=bilibili_config.cookies,
)

HEADER = Struct(">I2H2I")


async def heartbeat(conn: websockets.WebSocketClientProtocol) -> None:
    while True:
        await conn.send(dumps(b"", 1, 2))
        await sleep(30)


async def connect(roomid: int) -> AsyncGenerator[dict, None]:
    while True:
        with suppress(Exception):
            info = await get_danmu_info(roomid)
            host = info["host_list"][0]

            conn = await websockets.connect(
                f"wss://{host['host']}/sub",
                origin=websockets.Origin("https://live.bilibili.com"),
                user_agent_header="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
            )

            await conn.send(
                dumps(
                    json.dumps(
                        {
                            "uid": int(bilibili_config.cookies["DedeUserID"]),
                            "roomid": roomid,
                            "protover": 3,
                            # "buvid": bilibili_config.cookies["buvid3"],
                            "platform": "web",
                            "type": 2,
                            "key": info["token"],
                        }
                    ).encode(),
                    1,
                    7,
                )
            )
            data, *_ = loads(await conn.recv())  # type: ignore
            assert json.loads(data)["code"] == 0
            task = run_task(heartbeat(conn))

            async for data in conn:
                data = bytearray(data)  # type: ignore

                while data:
                    event, size, protover, _ = loads(data)
                    del data[:size]

                    match protover:
                        case 0:
                            yield json.loads(event)
                        case 1:
                            pass
                        case 2 | 3:
                            data = bytearray(event)

            task.cancel()


async def get_danmu_info(roomid: int) -> dict:
    return raise_for_status(
        await client.get(
            "https://api.live.bilibili.com/xlive/web-room/v1/index/getDanmuInfo",
            params={"id": roomid, "type": 0},
        )
    )


def dumps(data: bytes, protover: int, op: int) -> bytes:
    match protover:
        case 2:
            data = zlib.compress(data)
        case 3:
            data = brotli.compress(data)

    return HEADER.pack(len(data) + 16, 16, protover, op, 1) + data


def loads(data: bytes) -> tuple[bytes, int, int, int]:
    header = HEADER.unpack_from(data)
    data = data[16:]

    match header[2]:
        case 2:
            data = zlib.decompress(data)
        case 3:
            data = brotli.decompress(data)

    return data, header[0], header[2], header[3]
