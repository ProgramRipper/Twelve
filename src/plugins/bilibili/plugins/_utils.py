import re
import string
from random import choices
from typing import Any

from aiocache import cached
from httpx import AsyncClient, Response


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
    }
)

URL_PATTERN = re.compile(r"https://b23\.tv/\w+")


@cached(60 * 60 * 24)
async def get_short_url(oid: Any, origin: str) -> str:
    data = raise_for_status(
        await client.post(
            "https://api.bilibili.com/x/share/click",
            data={
                "oid": oid,
                "platform": "ios",
                "share_id": " ",
                "share_mode": 3,
                "share_origin": origin,
                "share_channel": "COPY",
                "build": "75400100",
                "buvid": "".join(choices(string.digits + string.ascii_uppercase, k=36)),
            },
        )
    )

    return next(URL_PATTERN.finditer(data["content"])).group()
