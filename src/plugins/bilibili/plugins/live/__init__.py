from asyncio import gather
from collections import defaultdict
from collections.abc import Coroutine
from typing import NoReturn

from arclet.alconna import Arg
from httpx import AsyncClient
from nonebot import get_driver, logger
from nonebot.plugin import PluginMetadata
from nonebot_plugin_alconna import Alconna, on_alconna
from nonebot_plugin_apscheduler import scheduler
from nonebot_plugin_orm import async_scoped_session, get_session
from nonebot_plugin_session import EventSession
from nonebot_plugin_session_orm import get_session_persist_id
from sqlalchemy import select

from .....utils import run_task, send_message
from .._utils import get_short_url, raise_for_status
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

room_infos: dict[str, RoomInfo] = {}
room_subs: dict[int, set[Subscription]] = defaultdict(set)
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
            room_subs[sub.uid].add(sub)

    if not room_subs:
        return

    room_infos = raise_for_status(
        await client.post(GET_ROOM_STATUS_INFO_URL, json={"uids": list(room_subs)})
    )


@scheduler.scheduled_job("interval", seconds=config.interval)
async def _() -> None:
    global room_infos

    if not (room_infos and (uids := list(filter(room_subs.__getitem__, room_subs)))):
        return

    old_room_infos, room_infos = room_infos, raise_for_status(
        await client.post(GET_ROOM_STATUS_INFO_URL, json={"uids": uids})
    )

    run_task(broadcast(old_room_infos))


async def broadcast(old_room_infos: dict[str, RoomInfo]) -> None:
    tasks: list[Coroutine] = []

    for uid, info in room_infos.items():
        uid = int(uid)

        if not info["live_status"] ^ old_room_infos[str(uid)]["live_status"]:
            continue

        url = await get_short_url(info["room_id"], "vertical-three-point")

        if info["live_status"]:
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


matcher = on_alconna(Alconna("订阅B站直播", Arg("uid", int)))


@matcher.handle()
async def _(db: async_scoped_session, sess: EventSession, uid: int) -> NoReturn:
    try:
        data = raise_for_status(
            await client.post(GET_ROOM_STATUS_INFO_URL, json={"uids": [uid]})
        )
    except Exception:
        logger.error("获取直播间信息失败")
        await matcher.send("获取直播间信息失败")
        raise

    try:
        room_infos[str(uid)] = info = data[str(uid)]
    except KeyError:
        await matcher.finish(f"用户不存在或未开通直播间")

    sub = Subscription(uid=uid, session_id=await get_session_persist_id(sess))
    if sub in room_subs[uid]:
        await matcher.finish(
            f"已订阅 {info['uname']} (UID:{uid}) 的直播间 ({info['room_id']})"
        )

    db.add(sub)
    await db.commit()
    room_subs[uid].add(sub)
    await matcher.finish(f"成功订阅 {info['uname']} (UID:{uid}) 的直播间 ({info['room_id']})")


matcher = on_alconna(Alconna("取订B站直播", Arg("uid", int)))


@matcher.handle()
async def _(db: async_scoped_session, sess: EventSession, uid: int) -> NoReturn:
    sub = Subscription(uid=uid, session_id=await get_session_persist_id(sess))
    if sub not in room_subs[uid]:
        await matcher.finish(f"未订阅 UID:{uid} 的直播间")

    await db.delete(await db.merge(sub))
    await db.commit()
    room_subs[uid].remove(sub)

    await matcher.finish(f"成功取消订阅 UID:{uid} 的直播间")


matcher = on_alconna(Alconna("列出B站直播"))


@matcher.handle()
async def _(db: async_scoped_session, sess: EventSession) -> NoReturn:
    subs = (
        await db.scalars(
            select(Subscription).where(
                Subscription.session_id == await get_session_persist_id(sess)
            )
        )
    ).all()
    if not subs:
        await matcher.finish(f"没有订阅直播间")

    await matcher.finish(
        "已订阅直播间:\n"
        + "\n".join(
            "{uname} (UID:{uid})".format_map(room_infos[str(sub.uid)]) for sub in subs
        )
    )
