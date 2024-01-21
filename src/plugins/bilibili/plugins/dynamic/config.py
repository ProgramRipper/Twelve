from typing import Any

from nonebot_plugin_alconna import UniMessage
from nonebot_plugin_alconna.uniseg.template import UniMessageTemplate
from pydantic import BaseConfig, BaseModel, Extra, validator

from src.utils import with_prefix


class Config(BaseModel):
    interval: int = 10
    screenshot_device: dict[str, Any] = {
        "user_agent": "Mozilla/5.0 (Linux; Android 7.0; Moto G (4)) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.28 Mobile Safari/537.36",
        "viewport": {"width": 360, "height": 640},
        "device_scale_factor": 3,
        "is_mobile": True,
        "has_touch": True,
        "default_browser_type": "chromium",
    }
    template: UniMessageTemplate = UniMessage.template(
        "{name} {action}{screenshot}{url}"
    )
    types: dict[str, str] = {
        "DYNAMIC_TYPE_ARTICLE": "投稿了文章",
        "DYNAMIC_TYPE_AV": "投稿了视频",
        "DYNAMIC_TYPE_DRAW": "发布了图文动态",
        # "DYNAMIC_TYPE_LIVE_RCMD": "直播了",
        "DYNAMIC_TYPE_WORD": "发布了文字动态",
        "DYNAMIC_TYPE_FORWARD": "转发了动态",
    }

    @validator("template", pre=True)
    @classmethod
    def parse_template(cls, v) -> UniMessageTemplate:
        return UniMessage.template(v)

    class Config(BaseConfig):
        alias_generator = with_prefix("bilibili_dynamic")
        arbitrary_types_allowed = True
        extra = Extra.ignore
