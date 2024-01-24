from pydantic import BaseConfig, BaseModel, Extra

from ...utils import with_prefix


class Config(BaseModel):
    cookies: dict[str, str]

    class Config(BaseConfig):
        alias_generator = with_prefix("bilibili")
        arbitrary_types_allowed = True
        extra = Extra.ignore
