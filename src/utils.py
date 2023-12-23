from asyncio import Task, create_task
from collections.abc import Callable
from inspect import iscoroutine
from operator import itemgetter
from types import NoneType
from typing import Awaitable, TypeVar

from nonebot import get_bot
from nonebot_plugin_alconna import AtAll, Target, UniMessage
from nonebot_plugin_alconna.uniseg import Receipt
from nonebot_plugin_session import Session, SessionIdType, SessionLevel

try:
    from nonebot.adapters.onebot.v11 import Bot as OneBot11Bot
except ImportError:
    OneBot11Bot = NoneType

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


def session_to_target(sess: Session) -> Target:
    return Target(
        sess.get_id(
            SessionIdType.TYPE2,
            include_platform=False,
            include_bot_type=False,
            include_bot_id=False,
        ),
        sess.get_id(
            SessionIdType.TYPE4,
            include_platform=False,
            include_bot_type=False,
            include_bot_id=False,
        ),
        sess.level == SessionLevel.CHANNEL,
        sess.level == SessionLevel.PRIVATE,
    )


async def send_message(sess: Session, msg: UniMessage) -> Receipt:
    bot = get_bot()
    target = session_to_target(sess)

    if isinstance(bot, OneBot11Bot) and not target.private and AtAll in msg:
        remain = await bot.get_group_at_all_remain(group_id=target.parent_id)
        if not all(
            itemgetter(
                "can_at_all",
                "remain_at_all_count_for_group",
                "remain_at_all_count_for_uin",
            )(remain)
        ):
            msg = msg.exclude(AtAll)

    return await msg.send(target, bot)


def with_prefix(prefix: str) -> Callable[[str], str]:
    return lambda name: f"{prefix}_{name}"
