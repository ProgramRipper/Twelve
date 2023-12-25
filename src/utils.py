from asyncio import Task, create_task
from collections.abc import Callable
from inspect import iscoroutine
from operator import itemgetter
from re import Match
from typing import Any, Awaitable, Literal, TypeVar, overload

from nonebot import get_bot
from nonebot.adapters.onebot.v11 import Bot as OneBot11Bot
from nonebot.adapters.onebot.v11.permission import (
    GROUP_ADMIN,
    GROUP_OWNER,
    PRIVATE_FRIEND,
)
from nonebot.adapters.qq.permission import GUILD_ADMIN, GUILD_CHANNEL_ADMIN, GUILD_OWNER
from nonebot.consts import REGEX_MATCHED
from nonebot.params import Depends
from nonebot.permission import SUPERUSER
from nonebot.typing import T_State
from nonebot_plugin_alconna import AtAll, Target, UniMessage
from nonebot_plugin_alconna.uniseg import Receipt
from nonebot_plugin_session import Session, SessionIdType, SessionLevel

T = TypeVar("T")


tasks: set[Task] = set()

ADMIN = (
    SUPERUSER
    | PRIVATE_FRIEND
    | GROUP_ADMIN
    | GROUP_OWNER
    | GUILD_CHANNEL_ADMIN
    | GUILD_ADMIN
    | GUILD_OWNER
)


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


def _regex_matched(state: T_State) -> Match[str]:
    return state[REGEX_MATCHED]


def _regex_str(
    groups: tuple[str | int, ...]
) -> Callable[[T_State], str | tuple[str | Any, ...] | Any]:
    def _regex_str_dependency(
        state: T_State,
    ) -> str | tuple[str | Any, ...] | Any:
        return _regex_matched(state).group(*groups)

    return _regex_str_dependency


@overload
def RegexStr(__group: Literal[0] = 0) -> str:
    ...


@overload
def RegexStr(__group: str | int) -> str | Any:
    ...


@overload
def RegexStr(
    __group1: str | int, __group2: str | int, *groups: str | int
) -> tuple[str | Any, ...]:
    ...


def RegexStr(*groups: str | int) -> str | tuple[str | Any, ...] | Any:
    """正则匹配结果文本"""
    return Depends(_regex_str(groups), use_cache=False)
