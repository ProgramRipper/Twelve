from asyncio import Task, create_task
from collections.abc import Callable
from inspect import iscoroutine
from typing import TYPE_CHECKING, Awaitable, TypeVar, cast

from httpx import AsyncClient
from nonebot_plugin_alconna import AtAll, SupportAdapter, UniMessage
from nonebot_plugin_alconna.uniseg import Receipt
from nonebot_plugin_uninfo.orm import SceneModel, get_bot_model
from nonebot_plugin_uninfo.target import to_target

if TYPE_CHECKING:
    from nonebot.adapters.milky.model.api import MessageResponse


T = TypeVar("T")


tasks: set[Task] = set()


async def await_(awaitable: Awaitable[T]) -> T:
    return await awaitable


def run_task(awaitable: Awaitable[T]) -> Task[T]:
    if isinstance(awaitable, Task):
        task = awaitable
    elif iscoroutine(awaitable):
        task = create_task(awaitable)
    else:
        task = create_task(await_(awaitable))

    tasks.add(task)
    task.add_done_callback(tasks.remove)

    return task


async def send_message(scene_model: SceneModel, msg: UniMessage) -> Receipt:
    bot_model = await get_bot_model(scene_model.bot_persist_id)

    target = to_target(await scene_model.to_scene(), bot_model.scope, without_self=True)
    bot = bot_model.get_bot()

    receipt = await msg.send(target, bot)

    if (
        bot_model.adapter == SupportAdapter.milky
        and cast("MessageResponse", receipt.msg_ids[0]).message_seq == 0
    ):
        receipt = await msg.exclude(AtAll).send(target, bot)

    return receipt


def with_prefix(prefix: str) -> Callable[[str], str]:
    return lambda name: f"{prefix}_{name}"


client = AsyncClient(
    headers={
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
    }
)
