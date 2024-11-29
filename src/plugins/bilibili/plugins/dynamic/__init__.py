from asyncio import gather
from collections import defaultdict
from contextlib import asynccontextmanager
from queue import PriorityQueue
from typing import Any, AsyncGenerator

import backoff
from arclet.alconna import Arg
from httpx import AsyncClient
from nonebot import get_driver, get_plugin_config, logger
from nonebot.plugin import PluginMetadata
from nonebot_plugin_alconna import Alconna, Image, UniMessage, on_alconna
from nonebot_plugin_apscheduler import scheduler
from nonebot_plugin_htmlrender import get_browser, get_new_page
from nonebot_plugin_orm import async_scoped_session, get_session
from nonebot_plugin_session import EventSession
from nonebot_plugin_session_orm import get_session_persist_id
from playwright.async_api import BrowserContext, Page, TimeoutError
from sqlalchemy import select

from .....utils import ADMIN, run_task, send_message
from ... import plugin_config as bilibili_config
from .._utils import get_share_click, raise_for_status
from .config import Config
from .models import Dynamic, Dynamics, Subscription

__plugin_meta__ = PluginMetadata(
    name="bilibili.dynamic",
    description="",
    usage="",
    config=Config,
)

driver = get_driver()
global_config = get_driver().config
plugin_config = get_plugin_config(Config)

context: BrowserContext
dynamic_subs: dict[str, set[Subscription]] = defaultdict(set)
client = AsyncClient(
    headers={
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
    },
    cookies=bilibili_config.cookies,
    base_url="https://api.bilibili.com/x",
)


class Cache:
    data: set[str]
    queue: PriorityQueue[str]

    def __init__(self) -> None:
        self.data = set()
        self.queue = PriorityQueue()

    def push(self, item: str) -> None:
        if item in self.data:
            return
        self.queue.put_nowait(item)
        self.data.add(item)

    def pop(self) -> str:
        item = self.queue.get_nowait()
        self.data.remove(item)
        return item

    def replace(self, item: str) -> str | None:
        if item < self.queue.queue[0] or item in self.data:
            return
        self.push(item)
        return self.pop()


cache = Cache()


@driver.on_startup
async def _() -> None:
    global context

    context = await (await get_browser()).new_context(**plugin_config.screenshot_device)
    await context.add_cookies(
        [
            {"name": name, "value": value, "domain": ".bilibili.com", "path": "/"}
            for name, value in bilibili_config.cookies.items()
        ]
    )
    await context.add_cookies(
        [
            {
                "name": "SESSDATA",
                "value": bilibili_config.cookies["SESSDATA"],
                "domain": ".bilibili.com",
                "path": "/",
                "httpOnly": True,
                "secure": True,
            }
        ]
    )

    for page in range(4, -1, -1):
        for item in (await get_dynamics(page))["items"]:
            cache.push(item["id_str"])

    async with get_session() as session:
        for sub in await session.scalars(select(Subscription)):
            dynamic_subs[str(sub.uid)].add(sub)


@scheduler.scheduled_job("interval", seconds=plugin_config.interval)
async def _() -> None:
    if not next(filter(dynamic_subs.__getitem__, dynamic_subs), None):
        return

    dynamics = []
    for dynamic in (await get_dynamics())["items"]:
        if cache.replace(dynamic["id_str"]):
            dynamics.append(dynamic)

    run_task(
        gather(
            *(
                broadcast(dynamic)
                for dynamic in dynamics
                if dynamic["type"] in plugin_config.types
            )
        )
    )


async def get_dynamics(page: int = 1) -> Dynamics:
    return raise_for_status(
        await client.get(
            "/polymer/web-dynamic/v1/feed/all",
            params={
                "type": "all",
                "page": page,
                "features": ",".join(
                    ("itemOpusStyle", "listOnlyfans", "opusBigCover", "onlyfansVote")
                ),
            },
        )
    )


async def broadcast(dynamic: Dynamic):
    uids = {str(dynamic["modules"]["module_author"]["mid"])}

    if dynamic["type"] in (
        "DYNAMIC_TYPE_DRAW",
        "DYNAMIC_TYPE_WORD",
        "DYNAMIC_TYPE_FORWARD",
    ):
        if dynamic["type"] == "DYNAMIC_TYPE_FORWARD":
            nodes = dynamic["modules"]["module_dynamic"]["desc"]["rich_text_nodes"]
        else:
            nodes = dynamic["modules"]["module_dynamic"]["major"]["opus"]["summary"][
                "rich_text_nodes"
            ]

        for node in nodes:
            if node["type"] == "RICH_TEXT_NODE_TYPE_AT":
                uids.add(node["rid"])

    sessions = {sub.session for uid in uids for sub in dynamic_subs.get(uid, ())}

    if not sessions:
        return

    screenshot, url = await gather(
        render_screenshot(dynamic),
        get_share_click(dynamic["id_str"], "dynamic", "dt.dt-detail.0.0.pv"),
    )
    message = plugin_config.template.format(
        name=dynamic["modules"]["module_author"]["name"],
        action=dynamic["modules"]["module_author"]["pub_action"]
        or plugin_config.types[dynamic["type"]],
        screenshot=Image(raw=screenshot),
        url=url,
    )

    await gather(*(send_message(sess.session, message) for sess in sessions))


@backoff.on_exception(backoff.constant, TimeoutError, max_tries=3)
async def render_screenshot(dynamic: Dynamic) -> bytes:
    async with get_new_page() as page:
        await page.goto(f"https://t.bilibili.com/{dynamic['id_str']}")
        await page.wait_for_load_state("networkidle")

        if "opus" in page.url:
            remove = ".opus-nav,.float-openapp,.openapp-dialog,.opus-read-more"
            target = ".opus-modules"
            await page.locator(".opus-module-content").evaluate(
                "e => e.classList.remove('limit')"
            )
        elif "dynamic" in page.url:
            remove = ".m-navbar,.dynamic-float-openapp,.dyn-share"
            target = ".dyn-card"
        else:
            remove = ""
            target = "body"

        await page.locator(remove).evaluate_all(
            "es => es.forEach(e => e.parentNode.removeChild(e))"
        )
        screenshot = await page.locator(target).first.screenshot()

    return screenshot


@asynccontextmanager
async def get_new_page(**kwargs) -> AsyncGenerator[Page, Any]:
    page = await context.new_page(**kwargs)
    try:
        yield page
    finally:
        await page.close()


@on_alconna(
    Alconna("订阅B站动态", Arg("uid", r"re:(?:UID:)?\d+")), permission=ADMIN
).handle()
async def _(db: async_scoped_session, sess: EventSession, uid: str):
    uid = uid.removeprefix("UID:")
    if not dynamic_subs[uid]:
        try:
            if raise_for_status(await client.get("/relation", params={"fid": uid}))[
                "attribute"
            ] not in {1, 2, 6}:
                await modify_relation(uid, 1)
        except Exception:
            logger.error("订阅B站动态失败")
            await UniMessage("订阅B站动态失败").send()
            raise

    sub = Subscription(uid=int(uid), session_id=await get_session_persist_id(sess))
    if sub in dynamic_subs[uid]:
        return await UniMessage(f"已订阅 UID:{uid} 的动态").send()

    db.add(sub)
    await db.commit()
    await db.refresh(sub, ["session"])
    dynamic_subs[uid].add(sub)

    await UniMessage(f"成功订阅 UID:{uid} 的动态").send()


@on_alconna(
    Alconna("取订B站动态", Arg("uid", r"re:(?:UID:)?\d+")), permission=ADMIN
).handle()
async def _(db: async_scoped_session, sess: EventSession, uid: str):
    uid = uid.removeprefix("UID:")
    sub = Subscription(uid=int(uid), session_id=await get_session_persist_id(sess))
    if sub not in dynamic_subs[uid]:
        return await UniMessage(f"未订阅 UID:{uid} 的动态").send()

    await db.delete(await db.merge(sub))
    await db.commit()
    dynamic_subs[uid].remove(sub)

    if not dynamic_subs[uid]:
        try:
            if raise_for_status(await client.get("/relation", params={"fid": uid}))[
                "attribute"
            ] in {1, 2, 6}:
                await modify_relation(uid, 2)
        except Exception:
            logger.error("取消关注失败")

    await UniMessage(f"成功取订 UID:{uid} 的动态").send()


async def modify_relation(uid: str, act: int) -> None:
    raise_for_status(
        await client.post(
            "/relation/modify",
            data={"fid": uid, "act": act, "csrf": client.cookies["bili_jct"]},
        )
    )


@on_alconna(Alconna("列出B站动态"), permission=ADMIN).handle()
async def _(db: async_scoped_session, sess: EventSession):
    subs = (
        await db.scalars(
            select(Subscription).where(
                Subscription.session_id == await get_session_persist_id(sess)
            )
        )
    ).all()
    if not subs:
        return await UniMessage(f"没有订阅动态").send()

    await UniMessage(
        "已订阅动态:\n" + "\n".join(f"UID:{sub.uid}" for sub in subs)
    ).send()
