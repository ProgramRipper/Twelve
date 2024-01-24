from typing import TypedDict

from nonebot_plugin_orm import Model
from nonebot_plugin_session_orm import SessionModel
from sqlalchemy import BigInteger, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship


class RoomInfo(TypedDict):
    title: str
    room_id: int
    uid: int
    live_time: int
    live_status: int
    uname: str
    cover_from_user: str


class Subscription(Model):
    uid: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey(SessionModel.id), primary_key=True
    )
    session: Mapped[SessionModel] = relationship(lazy=False, cascade="expunge")

    def __eq__(self, __value: object) -> bool:
        return (
            isinstance(__value, Subscription)
            and self.uid == __value.uid
            and self.session_id == __value.session_id
        )

    def __hash__(self) -> int:
        return hash((self.uid, self.session_id))
