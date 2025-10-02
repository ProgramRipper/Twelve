from asyncio import gather
from contextlib import asynccontextmanager
from importlib.resources import as_file, files
from queue import PriorityQueue
from typing import Annotated, Any, AsyncGenerator

import backoff
from arclet.alconna import Arg
from httpx import AsyncClient
from nonebot import get_driver, get_plugin_config
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata
from nonebot_plugin_alconna import Alconna, Image, Subcommand, UniMessage, on_alconna
from nonebot_plugin_apscheduler import scheduler
from nonebot_plugin_htmlkit import template_to_pic
from nonebot_plugin_htmlrender.browser import get_browser
from nonebot_plugin_orm import async_scoped_session, get_session
from nonebot_plugin_uninfo import MEMBER
from nonebot_plugin_uninfo.orm import SceneModel, SceneOrm
from playwright.async_api import BrowserContext, Page
from sqlalchemy import exists, select

from .....utils import run_task, send_message
from ... import plugin_config as bilibili_config
from ...utils import UID_ARG, get_share_click, handle_error, raise_for_status
from . import templates
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

client = AsyncClient(
    headers={
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
    },
    cookies=bilibili_config.cookies,
    base_url="https://api.bilibili.com/x",
)


async def img_fetch_fn(url: str) -> bytes:
    return (await client.get(url + "@.avif")).content


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


async def get_dynamics(page: int = 1) -> Dynamics:
    return raise_for_status(
        await client.get(
            "/polymer/web-dynamic/v1/feed/all",
            params={
                "type": "all",
                "page": page,
                "features": ",".join(
                    (
                        "itemOpusStyle",
                        "listOnlyfans",
                        "opusBigCover",
                        "onlyfansVote",
                        "decorationCard",
                        "onlyfansAssetsV2",
                        "forwardListHidden",
                        "ugcDelete",
                        "onlyfansQaCard",
                        "commentsNewVersion",
                        "avatarAutoTheme",
                    )
                ),
            },
        )
    )


async def get_relation(uid: int) -> int:
    return raise_for_status(await client.get("/relation", params={"fid": uid}))[
        "attribute"
    ]


async def modify_relation(uid: int, act: int) -> None:
    raise_for_status(
        await client.post(
            "/relation/modify",
            data={"fid": uid, "act": act, "csrf": client.cookies["bili_jct"]},
        )
    )


_context: BrowserContext | None = None


async def get_context() -> BrowserContext:
    global _context

    if _context and _context.browser and _context.browser.is_connected():
        return _context

    _context = await (await get_browser()).new_context(
        **plugin_config.screenshot_device
    )
    await _context.add_cookies(
        [
            {"name": name, "value": value, "domain": ".bilibili.com", "path": "/"}
            for name, value in bilibili_config.cookies.items()
        ]
    )
    await _context.add_cookies(
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

    pattern = "@540w_540h_1c.webp"
    await _context.route(
        "**/*" + pattern,
        lambda route: route.continue_(
            url=route.request.url[: -len(pattern)] + "@540w_540h_1c_!header.webp"
        ),
    )

    return _context


@asynccontextmanager
async def get_new_page(**kwargs) -> AsyncGenerator[Page, Any]:
    async with await (await get_context()).new_page(**kwargs) as page:
        await (await page.context.new_cdp_session(page)).send(
            "Network.setCacheDisabled", {"cacheDisabled": False}
        )
        yield page


@backoff.on_exception(backoff.constant, Exception, max_tries=3)
async def render_screenshot(id_str: str) -> bytes:
    async with get_new_page() as page:
        await page.goto(
            f"https://m.bilibili.com/opus/{id_str}", wait_until="domcontentloaded"
        )
        await page.add_style_tag(
            content="""
                body {
                  font-family: "LXGW ZhenKai GB", "LXGW WenKai GB", sans-serif !important;
                }

                :not(
                  .opus-modules,
                  .dyn-card,
                  .opus-modules *,
                  .dyn-card *,
                  :has(.opus-modules, .dyn-card)
                ),
                .opus-read-more,
                .opus-module-stat,
                .dyn-share {
                  display: none !important;
                }
                .opus-module-content.limit {
                  overflow: unset !important;
                  max-height: unset !important;
                  position: unset !important;
                  padding-bottom: unset !important;
                }
            """
        )
        await page.wait_for_load_state("networkidle")
        screenshot = await page.locator(".opus-modules, .dyn-card").first.screenshot(
            type="jpeg"
        )

    return screenshot


async def broadcast(dynamics: list[Dynamic]):
    async with get_session() as session:
        for dynamic in dynamics:
            with as_file(files(templates)) as templates_path:
                screenshot, url, subs = await gather(
                    (
                        template_to_pic(
                            str(templates_path),
                            "draw.html.j2",
                            dynamic,
                            max_width=360 * 3,
                            device_height=640 * 3,
                            img_fetch_fn=img_fetch_fn,
                            allow_refit=False,
                            image_format="jpeg",
                            jpeg_quality=80,
                        )
                        if dynamic["type"] == "DYNAMIC_TYPE_WORD"
                        or (
                            dynamic["type"] == "DYNAMIC_TYPE_DRAW"
                            and not dynamic["modules"]["module_dynamic"]["additional"]
                        )
                        else render_screenshot(dynamic["id_str"])
                    ),
                    get_share_click(
                        dynamic["id_str"], "dynamic", "dt.dt-detail.0.0.pv"
                    ),
                    session.scalars(
                        select(Subscription).where(
                            Subscription.uid
                            == dynamic["modules"]["module_author"]["mid"]
                        )
                    ),
                )

            msg = plugin_config.template.format(
                name=dynamic["modules"]["module_author"]["name"],
                action=dynamic["modules"]["module_author"]["pub_action"]
                or plugin_config.types[dynamic["type"]],
                screenshot=Image(raw=screenshot),
                url=url,
            )
            run_task(gather(*(send_message(sub.scene, msg) for sub in subs)))


@driver.on_startup
async def _() -> None:
    for page in range(1, 5):
        for item in (await get_dynamics(page))["items"]:
            cache.push(item["id_str"])


@scheduler.scheduled_job("interval", seconds=plugin_config.interval)
async def _() -> None:
    run_task(
        broadcast(
            [
                dynamic
                for dynamic in (await get_dynamics())["items"]
                if cache.replace(dynamic["id_str"])
                and dynamic["type"] in plugin_config.types
            ]
        )
    )


cmd = on_alconna(
    Alconna(
        "B站动态",
        Subcommand("订阅", UID_ARG),
        Subcommand("取订", UID_ARG),
        Subcommand("列出"),
        Subcommand("展示", Arg("id_str", r"re:\d+")),
    ),
    permission=SUPERUSER | MEMBER(),
)


@cmd.assign("订阅")
async def _(
    db: async_scoped_session, scene: Annotated[SceneModel, SceneOrm()], uid: int
):
    if await db.get(Subscription, (uid, scene.id)):
        return await UniMessage(f"已订阅 UID:{uid} 的动态").send()

    if not await db.scalar(select(exists().where(Subscription.uid == uid))):
        try:
            if await get_relation(uid) not in {1, 2, 6}:
                await modify_relation(uid, 1)
        except Exception:
            await handle_error("订阅B站动态失败")

    db.add(Subscription(uid=uid, scene_id=scene.id))
    await db.commit()
    await UniMessage(f"成功订阅 UID:{uid} 的动态").send()


@cmd.assign("取订")
async def _(
    db: async_scoped_session, scene: Annotated[SceneModel, SceneOrm()], uid: int
):
    if not (sub := await db.get(Subscription, (uid, scene.id))):
        return await UniMessage(f"未订阅 UID:{uid} 的动态").send()

    await db.delete(sub)

    if not await db.scalar(select(exists().where(Subscription.uid == uid))):
        try:
            if await get_relation(uid) in {1, 2, 6}:
                await modify_relation(uid, 2)
        except Exception:
            await handle_error("取订B站动态失败")

    await db.commit()
    await UniMessage(f"成功取订 UID:{uid} 的动态").send()


@cmd.assign("列出")
async def _(db: async_scoped_session, scene: Annotated[SceneModel, SceneOrm()]):
    if not (
        subs := (
            await db.scalars(select(Subscription).where(Subscription.scene == scene))
        ).all()
    ):
        return await UniMessage(f"没有订阅动态").send()

    await UniMessage(
        "已订阅动态:\n" + "\n".join(f"UID:{sub.uid}" for sub in subs)
    ).send()


@cmd.assign("展示")
async def _(id_str: str):
    try:
        dynamic = raise_for_status(
            await client.get(
                "/polymer/web-dynamic/v1/detail",
                params={
                    "id": id_str,
                    "features": ",".join(
                        (
                            "itemOpusStyle",
                            "listOnlyfans",
                            "opusBigCover",
                            "onlyfansVote",
                            "decorationCard",
                            "onlyfansAssetsV2",
                            "forwardListHidden",
                            "ugcDelete",
                            "onlyfansQaCard",
                            "commentsNewVersion",
                            "avatarAutoTheme",
                        )
                    ),
                },
            )
        )["item"]
    except Exception:
        await handle_error("获取动态信息失败")

    with as_file(files(templates)) as templates_path:
        screenshot, url = await gather(
            (
                template_to_pic(
                    str(templates_path),
                    "draw.html.j2",
                    dynamic,
                    max_width=360 * 3,
                    device_height=640 * 3,
                    img_fetch_fn=img_fetch_fn,
                    allow_refit=False,
                    image_format="jpeg",
                    jpeg_quality=80,
                )
                if dynamic["type"] == "DYNAMIC_TYPE_WORD"
                or (
                    dynamic["type"] == "DYNAMIC_TYPE_DRAW"
                    and not dynamic["modules"]["module_dynamic"]["additional"]
                )
                else render_screenshot(dynamic["id_str"])
            ),
            get_share_click(id_str, "dynamic", "dt.dt-detail.0.0.pv"),
        )
    await plugin_config.template.format(
        name=dynamic["modules"]["module_author"]["name"],
        action=dynamic["modules"]["module_author"]["pub_action"]
        or plugin_config.types.get(dynamic["type"], "发布了动态"),
        screenshot=Image(raw=screenshot),
        url=url,
    ).send()
