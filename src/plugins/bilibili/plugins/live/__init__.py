from asyncio import gather
from time import time
from typing import Annotated

from httpx import AsyncClient
from nonebot import get_driver, get_plugin_config
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata
from nonebot_plugin_alconna import (
    Alconna,
    AtAll,
    Image,
    Subcommand,
    UniMessage,
    on_alconna,
)
from nonebot_plugin_apscheduler import scheduler
from nonebot_plugin_orm import async_scoped_session, get_session
from nonebot_plugin_uninfo import MEMBER
from nonebot_plugin_uninfo.orm import SceneModel, SceneOrm
from sqlalchemy import select

from .....utils import run_task, send_message
from ...utils import UID_ARG, get_share_click, handle_error, raise_for_status
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

room_infos: dict[int, RoomInfo] = {}
client = AsyncClient(
    headers={
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
    }
)


async def get_status_info_by_uids(uids: list[int]) -> dict[int, RoomInfo]:
    return (
        {
            int(uid): info
            for uid, info in raise_for_status(
                await client.post(
                    "https://api.live.bilibili.com/room/v1/Room/get_status_info_by_uids",
                    json={"uids": uids},
                )
            ).items()
        }
        if uids
        else {}
    )


async def broadcast(uids: list[int]) -> None:
    async with get_session() as session:
        for uid in uids:
            info = room_infos[uid]
            subs = await session.scalars(
                select(Subscription).where(Subscription.uid == uid)
            )
            if info["live_status"] and time() - info["live_time"] < max(
                plugin_config.interval, 10
            ):
                cover, url = await gather(
                    client.get(info["cover_from_user"] or info["face"]),
                    get_share_click(
                        info["room_id"],
                        "vertical-three-point",
                        "live.live-room-detail.0.0.pv",
                    ),
                )

                msg = plugin_config.live_template.format(
                    url=url, cover=Image(raw=cover.content), **info
                )
            else:
                msg = plugin_config.preparing_template.format(**info)

            run_task(gather(*(send_message(sub.scene, msg) for sub in subs)))


@scheduler.scheduled_job("interval", seconds=plugin_config.interval)
async def _() -> None:
    async with get_session() as session:
        uids = list(await session.scalars(select(Subscription.uid)))

    curr_room_infos = await get_status_info_by_uids(uids)

    run_task(
        broadcast(
            [
                uid
                for uid in room_infos.keys() & curr_room_infos.keys()
                if room_infos[uid]["live_status"] ^ curr_room_infos[uid]["live_status"]
            ]
        )
    )

    room_infos.update(curr_room_infos)


cmd = on_alconna(
    Alconna(
        "B站直播",
        Subcommand("订阅", UID_ARG),
        Subcommand("取订", UID_ARG),
        Subcommand("列出"),
        Subcommand("展示", UID_ARG),
    ),
    permission=SUPERUSER | MEMBER(),
)


@cmd.assign("订阅")
async def _(
    db: async_scoped_session, scene: Annotated[SceneModel, SceneOrm()], uid: int
):
    if await db.get(Subscription, (uid, scene.id)):
        return await UniMessage(f"已订阅 UID:{uid} 的直播").send()

    if not (info := room_infos.get(uid)):
        try:
            infos = await get_status_info_by_uids([uid])
        except Exception:
            await handle_error("获取直播信息失败")

        try:
            info = infos[uid]
        except KeyError:
            return await UniMessage(f"用户不存在或未开通直播").send()

        room_infos[uid] = info

    db.add(Subscription(uid=uid, scene_id=scene.id))
    await db.commit()
    await UniMessage(
        f"成功订阅 {info['uname']} (UID:{uid}) 的直播 ({info['room_id']})"
    ).send()


@cmd.assign("取订")
async def _(
    db: async_scoped_session, scene: Annotated[SceneModel, SceneOrm()], uid: int
):
    if not (sub := await db.get(Subscription, (uid, scene.id))):
        return await UniMessage(f"未订阅 UID:{uid} 的直播").send()

    await db.delete(sub)
    await db.commit()
    await UniMessage(f"成功取订 UID:{uid} 的直播").send()


@cmd.assign("列出")
async def _(db: async_scoped_session, scene: Annotated[SceneModel, SceneOrm()]):
    if not (
        subs := (
            await db.scalars(select(Subscription).where(Subscription.scene == scene))
        ).all()
    ):
        return await UniMessage(f"没有订阅直播").send()

    await UniMessage(
        "已订阅直播:\n"
        + "\n".join(
            "{uname} (UID:{uid})".format_map(room_infos[sub.uid]) for sub in subs
        )
    ).send()


@cmd.assign("展示")
async def _(uid: int):
    try:
        info = (await get_status_info_by_uids([uid]))[uid]
    except Exception:
        await handle_error("获取直播信息失败")

    url, cover = await gather(
        get_share_click(
            info["room_id"], "vertical-three-point", "live.live-room-detail.0.0.pv"
        ),
        client.get(info["cover_from_user"] or info["face"]),
    )
    await plugin_config.live_template.format(
        url=url, cover=Image(raw=cover.content), **info
    ).exclude(AtAll).send()
