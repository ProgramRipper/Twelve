from asyncio import gather
from collections import defaultdict
from collections.abc import Coroutine
from time import time

from arclet.alconna import Arg
from httpx import AsyncClient
from nonebot import get_driver, get_plugin_config, logger
from nonebot.plugin import PluginMetadata
from nonebot_plugin_alconna import Alconna, Image, UniMessage, on_alconna
from nonebot_plugin_apscheduler import scheduler
from nonebot_plugin_orm import async_scoped_session, get_session
from nonebot_plugin_session import EventSession
from nonebot_plugin_session_orm import get_session_persist_id
from sqlalchemy import select

from .....utils import ADMIN, run_task, send_message
from .._utils import get_share_click, raise_for_status
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
plugin_config = get_plugin_config(Config)

room_infos: dict[str, RoomInfo] = {}
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
    global room_infos

    async with get_session() as session:
        for sub in await session.scalars(select(Subscription)):
            room_subs[str(sub.uid)].add(sub)

    if not room_subs:
        return

    room_infos = raise_for_status(
        await client.post(GET_ROOM_STATUS_INFO_URL, json={"uids": list(room_subs)})
    )


@scheduler.scheduled_job("interval", seconds=plugin_config.interval)
async def _() -> None:
    global room_infos

    if not (room_infos and (uids := list(filter(room_subs.__getitem__, room_subs)))):
        return

    curr_room_infos = raise_for_status(
        await client.post(GET_ROOM_STATUS_INFO_URL, json={"uids": uids})
    )

    run_task(
        broadcast(
            [
                uid
                for uid in uids
                if uid in curr_room_infos
                and curr_room_infos[uid]["live_status"] ^ room_infos[uid]["live_status"]
            ]
        )
    )

    room_infos.update(curr_room_infos)


async def broadcast(uids: list[str]) -> None:
    tasks: list[Coroutine] = []

    for uid in uids:
        info = room_infos[uid]

        if info["live_status"] and time() - info["live_time"] < max(
            plugin_config.interval, 10
        ):
            url = await get_share_click(
                info["room_id"], "vertical-three-point", "live.live-room-detail.0.0.pv"
            )
            cover = Image(
                raw=(await client.get(info["cover_from_user"] or info["face"])).content
            )

            for sub in room_subs[uid]:
                tasks.append(
                    send_message(
                        sub.session.session,
                        plugin_config.live_template.format(
                            url=url,
                            cover=cover,
                            **info,
                        ),
                    )
                )
        else:
            for sub in room_subs[uid]:
                tasks.append(
                    send_message(
                        sub.session.session,
                        plugin_config.preparing_template.format(**info),
                    )
                )

    await gather(*tasks)


@on_alconna(
    Alconna("订阅B站直播", Arg("uid", r"re:(?:UID:)?\d+")), permission=ADMIN
).handle()
async def _(db: async_scoped_session, sess: EventSession, uid: str):
    uid = uid.removeprefix("UID:")

    sub = Subscription(uid=int(uid), session_id=await get_session_persist_id(sess))
    if sub in room_subs[uid]:
        return await UniMessage(f"已订阅 UID:{uid} 的直播间").send()

    try:
        infos = raise_for_status(
            await client.post(GET_ROOM_STATUS_INFO_URL, json={"uids": [uid]})
        )
    except Exception:
        logger.error("获取直播间信息失败")
        await UniMessage("获取直播间信息失败").send()
        raise

    try:
        info = infos[uid]
    except KeyError:
        return await UniMessage(f"用户不存在或未开通直播间").send()

    db.add(sub)
    await db.commit()
    await db.refresh(sub, ["session"])
    room_subs[uid].add(sub)
    room_infos[uid] = info

    await UniMessage(
        f"成功订阅 {info['uname']} (UID:{uid}) 的直播间 ({info['room_id']})"
    ).send()


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

    await UniMessage(
        "已订阅直播间:\n"
        + "\n".join(
            "{uname} (UID:{uid})".format_map(room_infos[str(sub.uid)]) for sub in subs
        )
    ).send()
