from pathlib import Path

import nonebot
from nonebot import get_driver, get_plugin_config
from nonebot.plugin import PluginMetadata

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="bilibili",
    description="",
    usage="",
    config=Config,
)

global_config = get_driver().config
plugin_config = get_plugin_config(Config)

sub_plugins = nonebot.load_plugins(
    str(Path(__file__).parent.joinpath("plugins").resolve())
)
