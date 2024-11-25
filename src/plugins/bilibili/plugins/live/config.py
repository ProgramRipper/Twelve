from nonebot_plugin_alconna import UniMessage
from nonebot_plugin_alconna.uniseg.template import UniMessageTemplate
from pydantic import BaseConfig, BaseModel, Extra, validator

from src.utils import with_prefix


class Config(BaseModel):
    interval: int = 1
    live_template: UniMessageTemplate = UniMessage.template(
        "{:AtAll()} {uname} 正在直播 {title}{cover}{url}"
    )
    preparing_template: UniMessageTemplate = UniMessage.template("{uname} 下锅了")

    @validator("live_template", "preparing_template", pre=True)
    @classmethod
    def parse_template(cls, v) -> UniMessageTemplate:
        return UniMessage.template(v)

    class Config(BaseConfig):
        alias_generator = with_prefix("bilibili_live")
        arbitrary_types_allowed = True
        extra = Extra.ignore
