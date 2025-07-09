from typing import TypedDict

from nonebot_plugin_orm import Model
from nonebot_plugin_uninfo.orm import SceneModel
from sqlalchemy import BigInteger, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship


class ModuleAuthor(TypedDict):
    mid: int
    name: str
    pub_action: str


class Modules(TypedDict):
    module_author: ModuleAuthor


class Dynamic(TypedDict):
    id_str: str
    modules: Modules
    type: str


class Dynamics(TypedDict):
    has_more: bool
    items: list[Dynamic]
    update_baseline: str
    update_num: int


class Subscription(Model):
    uid: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    scene_id: Mapped[int] = mapped_column(ForeignKey(SceneModel.id), primary_key=True)
    scene: Mapped[SceneModel] = relationship(lazy=False, cascade="expunge")

    def __eq__(self, __value: object) -> bool:
        return (
            isinstance(__value, Subscription)
            and self.uid == __value.uid
            and self.scene_id == __value.scene_id
        )

    def __hash__(self) -> int:
        return hash((self.uid, self.scene_id))
