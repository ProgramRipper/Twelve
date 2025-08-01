"""initial revision

迁移 ID: 9a8b6ae112db
父迁移:
创建时间: 2023-12-23 16:39:26.978084

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9a8b6ae112db"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = "dynamic"
depends_on: str | Sequence[str] | None = "2e0c173949d3"


def upgrade(name: str = "") -> None:
    if name:
        return
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "dynamic_subscription",
        sa.Column("uid", sa.BigInteger(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["nonebot_plugin_session_orm_sessionmodel.id"],
            name=op.f(
                "fk_dynamic_subscription_session_id_nonebot_plugin_session_orm_sessionmodel"
            ),
        ),
        sa.PrimaryKeyConstraint(
            "uid", "session_id", name=op.f("pk_dynamic_subscription")
        ),
        info={"bind_key": "dynamic"},
    )
    # ### end Alembic commands ###


def downgrade(name: str = "") -> None:
    if name:
        return
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table("dynamic_subscription")
    # ### end Alembic commands ###
