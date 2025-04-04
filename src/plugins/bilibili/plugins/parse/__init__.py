from nonebot import get_driver, get_plugin_config, on_regex
from nonebot.plugin import PluginMetadata
from nonebot.rule import to_me
from nonebot_plugin_alconna import UniMessage

from .....utils import RegexStr
from .._utils import bv2av, get_share_placard
from .config import Config

__plugin_meta__ = PluginMetadata(
    name="bilibili.parse",
    description="",
    usage="",
    config=Config,
)

global_config = get_driver().config
plugin_config = get_plugin_config(Config)


TEMPLATE = UniMessage.template("{:Image(url=picture)}{link}")


@on_regex(r"(?:av|AV)(\d{1,16})", rule=to_me()).handle()
async def parse_aid(aid: str = RegexStr(1)):
    await TEMPLATE.format_map(
        await get_share_placard(aid, "main.ugc-video-detail.0.0.pv")
    ).send()


@on_regex(r"BV1[1-9a-km-zA-HJ-NP-Z]{9}", rule=to_me()).handle()
async def _(bvid: str = RegexStr()):
    await parse_aid(bv2av(bvid))


@on_regex(r"UID:(\d+)", rule=to_me()).handle()
async def _(uid: str = RegexStr(1)):
    await TEMPLATE.format_map(
        await get_share_placard(uid, "main.space-total.more.0.click")
    ).send()
