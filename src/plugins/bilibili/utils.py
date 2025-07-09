import re
import string
from random import choices
from typing import Any, NoReturn, TypedDict

from arclet.alconna import Arg
from httpx import AsyncClient, Response
from nepattern import BasePattern, MatchMode
from nonebot import logger
from nonebot_plugin_alconna import UniMessage

UID_ARG = Arg(
    "uid",
    BasePattern(
        r"(?:UID:)?(\d+)",
        MatchMode.REGEX_CONVERT,
        int,
        lambda _, match: int(match[1]),
    ),
)


def bv2av(bvid: str) -> int:
    bv = list(bvid[3:])

    bv[0], bv[6] = bv[6], bv[0]
    bv[1], bv[4] = bv[4], bv[1]

    tmp = 0
    for i in bv:
        tmp = (
            tmp * 58
            + "FcwAPNKTMug3GV5Lj7EJnHpWsx4tb8haYeviqBz6rkCy12mUSDQX9RdoZf".index(i)
        )

    return (tmp & 0x7FFFFFFFFFFFF) ^ 0x01552356C4CDB


def raise_for_status(resp: Response) -> Any:
    try:
        data = resp.json()
    except Exception:
        resp.raise_for_status()
        raise ValueError(f"Invalid response: {resp.content}")

    assert data["code"] == 0, data
    return data.get("data")


client = AsyncClient(
    headers={
        "user-agent": "bili-universal/75600100 CFNetwork/1.0 "
        "Darwin/23.2.0 os/ios model/iPhone 13 mini mobi_app/iphone "
        "build/75600100 osVer/17.2 network/1 channel/AppStore;tf:cm"
    },
    base_url="https://api.bilibili.com/x/share",
)

URL_PATTERN = re.compile(
    r"http[s]?://"
    r"(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|"
    r"(?:%[0-9a-fA-F][0-9a-fA-F]))+"
)


async def get_share_click(oid: Any, origin: str, share_id: str) -> str:
    data = raise_for_status(
        await client.post(
            "/click",
            data={
                "oid": oid,
                "share_id": share_id,
                "share_origin": origin,
                "platform": "ios",
                "share_channel": "COPY",
                "share_mode": 3,
                "build": "75400100",
                "buvid": "".join(choices(string.digits + string.ascii_uppercase, k=36)),
            },
        )
    )

    return next(URL_PATTERN.finditer(data["content"]))[0]


class SharePlacard(TypedDict):
    picture: str
    link: str


async def get_share_placard(oid: Any, share_id: str) -> SharePlacard:
    return raise_for_status(
        await client.post(
            "/placard",
            data={
                "oid": oid,
                "platform": "ios",
                "share_id": share_id,
                "buvid": "".join(choices(string.digits + string.ascii_uppercase, k=36)),
            },
        )
    )


async def handle_error(message: str) -> NoReturn:
    logger.error(message)
    await UniMessage(message).send()
    raise
