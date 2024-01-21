from asyncio import Task, gather
from collections import defaultdict
from collections.abc import Coroutine
from typing import NoReturn

from arclet.alconna import Arg
from httpx import AsyncClient
from nonebot import get_driver, logger
from nonebot.plugin import PluginMetadata
from nonebot_plugin_alconna import Alconna, UniMessage, on_alconna
from nonebot_plugin_orm import async_scoped_session, get_session
from nonebot_plugin_session import EventSession
from nonebot_plugin_session_orm import get_session_persist_id
from sqlalchemy import select

from .....utils import ADMIN, run_task, send_message
from .._utils import get_share_click, raise_for_status
from .blv import connect
from .config import Config
from .models import RoomInfo, Subscription

__plugin_meta__ = PluginMetadata(
    name="bilibili.live",
    description="",
    usage="",
    config=Config,
)

driver = get_driver()
global_config = driver.config
config = Config.parse_obj(global_config)

tasks: dict[str, Task] = {}
room_subs: dict[str, set[Subscription]] = defaultdict(set)
client = AsyncClient(
    headers={
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
    }
)

GET_ROOM_STATUS_INFO_URL = (
    "https://api.live.bilibili.com/room/v1/Room/get_status_info_by_uids"
)


@driver.on_startup
async def _() -> None:
    async with get_session() as session:
        for sub in await session.scalars(select(Subscription)):
            room_subs[str(sub.uid)].add(sub)

    if not room_subs:
        return

    infos: dict[str, RoomInfo] = raise_for_status(
        await client.post(GET_ROOM_STATUS_INFO_URL, json={"uids": list(room_subs)})
    )
    tasks.update(
        {uid: run_task(broadcast_task(uid, infos[uid]["room_id"])) for uid in room_subs}
    )


async def broadcast_task(uid: str, roomid: int) -> NoReturn:
    async for event in connect(roomid):
        match event["cmd"]:
            case "LIVE" if event["live_time"] is None:
                pass
            case "LIVE" | "PREPARING":
                await broadcast(uid)


async def broadcast(uid: str) -> None:
    tasks: list[Coroutine] = []
    info: RoomInfo = raise_for_status(
        await client.post(GET_ROOM_STATUS_INFO_URL, json={"uids": [uid]})
    )[uid]

    if info["live_status"]:
        url = await get_share_click(
            info["room_id"], "vertical-three-point", "live.live-room-detail.0.0.pv"
        )
        for sub in room_subs[uid]:
            tasks.append(
                send_message(
                    sub.session.session,
                    config.live_template.format(url=url, **info),
                )
            )
    else:
        for sub in room_subs[uid]:
            tasks.append(
                send_message(
                    sub.session.session, config.preparing_template.format(**info)
                )
            )

    await gather(*tasks)


@on_alconna(
    Alconna("订阅B站直播", Arg("uid", r"re:(?:UID:)?\d+")), permission=ADMIN
).handle()
async def _(db: async_scoped_session, sess: EventSession, uid: str):
    uid = uid.removeprefix("UID:")
    try:
        infos: dict[str, RoomInfo] = raise_for_status(
            await client.post(GET_ROOM_STATUS_INFO_URL, json={"uids": [uid]})
        )
    except Exception:
        logger.error("获取直播间信息失败")
        await UniMessage("获取直播间信息失败").send()
        raise

    try:
        roomid = infos[uid]["room_id"]
    except KeyError:
        return await UniMessage(f"用户不存在或未开通直播间").send()

    sub = Subscription(uid=int(uid), session_id=await get_session_persist_id(sess))
    if sub in room_subs[uid]:
        return await UniMessage(f"已订阅 UID:{uid} 的直播间").send()

    db.add(sub)
    await db.commit()
    await db.refresh(sub, ["session"])
    room_subs[uid].add(sub)

    if uid not in tasks:
        tasks[uid] = run_task(broadcast_task(uid, roomid))

    await UniMessage(f"成功订阅 UID:{uid} 的直播间").send()


@on_alconna(
    Alconna("取订B站直播", Arg("uid", r"re:(?:UID:)?\d+")), permission=ADMIN
).handle()
async def _(db: async_scoped_session, sess: EventSession, uid: str):
    uid = uid.removeprefix("UID:")
    sub = Subscription(uid=int(uid), session_id=await get_session_persist_id(sess))
    if sub not in room_subs[uid]:
        return await UniMessage(f"未订阅 UID:{uid} 的直播间").send()

    await db.delete(await db.merge(sub))
    await db.commit()
    room_subs[uid].remove(sub)

    if not room_subs[uid]:
        tasks.pop(uid).cancel()

    await UniMessage(f"成功取消订阅 UID:{uid} 的直播间").send()


@on_alconna(Alconna("列出B站直播"), permission=ADMIN).handle()
async def _(db: async_scoped_session, sess: EventSession):
    subs = (
        await db.scalars(
            select(Subscription).where(
                Subscription.session_id == await get_session_persist_id(sess)
            )
        )
    ).all()

    if not subs:
        return await UniMessage(f"没有订阅直播间").send()

    await UniMessage("已订阅直播间:\n" + "\n".join(f"UID:{sub.uid}" for sub in subs)).send()
