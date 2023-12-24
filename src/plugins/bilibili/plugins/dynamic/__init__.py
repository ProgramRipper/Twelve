from asyncio import gather
from collections import defaultdict
from contextlib import asynccontextmanager
from itertools import takewhile
from typing import Any, AsyncGenerator, NoReturn

from arclet.alconna import Arg
from httpx import AsyncClient
from nonebot import get_driver, logger
from nonebot.plugin import PluginMetadata
from nonebot_plugin_alconna import Alconna, Image, on_alconna
from nonebot_plugin_apscheduler import scheduler
from nonebot_plugin_htmlrender import get_browser, get_new_page
from nonebot_plugin_orm import async_scoped_session, get_session
from nonebot_plugin_session import EventSession
from nonebot_plugin_session_orm import get_session_persist_id
from playwright.async_api import BrowserContext, Page
from sqlalchemy import select

from .....utils import run_task, send_message
from .._utils import get_short_url, raise_for_status
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
plugin_config = Config.parse_obj(global_config)


context: BrowserContext
update_baseline: str = ""
dynamic_subs: dict[int, set[Subscription]] = defaultdict(set)
client = AsyncClient(
    headers={
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
    },
    cookies=plugin_config.cookies,
    base_url="https://api.bilibili.com/x",
)


@driver.on_startup
async def _() -> None:
    global context, update_baseline

    context = await (await get_browser()).new_context(**plugin_config.screenshot_device)
    await context.add_cookies(
        [
            {"name": name, "value": value, "domain": ".bilibili.com", "path": "/"}
            for name, value in plugin_config.cookies.items()
        ]
    )
    await context.add_cookies(
        [
            {
                "name": "SESSDATA",
                "value": plugin_config.cookies["SESSDATA"],
                "domain": ".bilibili.com",
                "path": "/",
                "httpOnly": True,
                "secure": True,
            }
        ]
    )

    update_baseline = (await get_dynamics())["update_baseline"]

    async with get_session() as session:
        for sub in await session.scalars(select(Subscription)):
            dynamic_subs[sub.uid].add(sub)


@scheduler.scheduled_job("interval", seconds=plugin_config.interval)
async def _() -> None:
    global update_baseline

    if not next(filter(dynamic_subs.__getitem__, dynamic_subs), None):
        return

    update_num: int = raise_for_status(
        await client.get(
            "/polymer/web-dynamic/v1/feed/all/update",
            params={"type": "all", "update_baseline": update_baseline},
        )
    )["update_num"]
    if not update_num:
        return

    data: Dynamics = None  # type:ignore
    dynamics: list[Dynamic] = []
    has_more: bool = True
    page = 1

    while has_more and len(dynamics) < update_num:
        data = await get_dynamics(page)

        update_num = data["update_num"]
        dynamics.extend(
            takewhile(lambda d: d["id_str"] > update_baseline, data["items"])
        )
        has_more = data["has_more"]
        page += 1

    update_baseline = data["update_baseline"]
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
                "update_baseline": update_baseline,
                "page": page,
                "features": ",".join(
                    ("itemOpusStyle", "listOnlyfans", "opusBigCover", "onlyfansVote")
                ),
            },
        )
    )


async def broadcast(dynamic: Dynamic):
    screenshot, url = await gather(
        render_screenshot(dynamic),
        get_short_url(dynamic["id_str"], "dynamic", "dt.dt-detail.0.0.pv"),
    )
    await gather(
        *[
            send_message(
                sub.session.session,
                plugin_config.template.format(
                    name=dynamic["modules"]["module_author"]["name"],
                    action=dynamic["modules"]["module_author"]["pub_action"]
                    or plugin_config.types[dynamic["type"]],
                    screenshot=Image(raw=screenshot),
                    url=url,
                ),
            )
            for sub in dynamic_subs[dynamic["modules"]["module_author"]["mid"]]
        ]
    )


async def render_screenshot(dynamic: Dynamic) -> bytes:
    async with get_new_page() as page:
        await page.goto(f"https://t.bilibili.com/{dynamic['id_str']}")
        await page.wait_for_load_state("networkidle")

        if "opus" in page.url:
            remove = ".float-openapp,.openapp-dialog"
            target = ".opus-modules"
        elif "dynamic" in page.url:
            remove = ".dynamic-float-openapp,.dyn-share"
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


matcher = on_alconna(Alconna("订阅B站动态", Arg("uid", int)))


@matcher.handle()
async def _(db: async_scoped_session, sess: EventSession, uid: int) -> NoReturn:
    if not dynamic_subs[uid]:
        try:
            if raise_for_status(await client.get("/relation", params={"fid": uid}))[
                "attribute"
            ] not in {1, 2, 6}:
                await modify_relation(uid, 1)
        except Exception:
            logger.error("订阅B站动态失败")
            await matcher.send("订阅B站动态失败")
            raise

    sub = Subscription(uid=uid, session_id=await get_session_persist_id(sess))
    if sub in dynamic_subs[uid]:
        await matcher.finish(f"已订阅 UID:{uid} 的动态")

    db.add(sub)
    await db.commit()
    await db.refresh(sub, ["session"])
    dynamic_subs[uid].add(sub)

    await matcher.finish(f"成功订阅 UID:{uid} 的动态")


matcher = on_alconna(Alconna("取订B站动态", Arg("uid", int)))


@matcher.handle()
async def _(db: async_scoped_session, sess: EventSession, uid: int) -> NoReturn:
    sub = Subscription(uid=uid, session_id=await get_session_persist_id(sess))
    if sub not in dynamic_subs[uid]:
        await matcher.finish(f"未订阅 UID:{uid} 的动态")

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

    await matcher.finish(f"成功取订 UID:{uid} 的动态")


async def modify_relation(uid: int, act: int) -> None:
    raise_for_status(
        await client.post(
            "/relation/modify",
            data={"fid": uid, "act": act, "csrf": client.cookies["bili_jct"]},
        )
    )


matcher = on_alconna(Alconna("列出B站动态"))


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
        await matcher.finish(f"没有订阅动态")

    await matcher.finish("已订阅动态:\n" + "\n".join(f"UID:{sub.uid}" for sub in subs))
