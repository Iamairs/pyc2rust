# https://github.com/Pythagora-io/gpt-pilot/blob/main/core/db/models/base.py
# DeclarativeBase enables declarative configuration of
# database models within SQLAlchemy.
#
# It also sets up a registry for the classes that inherit from it,
# so that SQLAlechemy understands how they map to database tables.
from typing import Optional, Self
from uuid import UUID, uuid4

from sqlalchemy import MetaData, select, delete
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, mapped_column, Mapped, ColumnProperty
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import JSON


class BaseTable(AsyncAttrs, DeclarativeBase):
    """
        基础数据库模型类，所有数据库表模型均应继承自此类。
        提供了一个 UUID 主键字段 `id`，并实现了一些通用的方法和属性。
        Attributes:
            id (str): 主键，使用 UUID 字符串表示，默认值为自动生成的 UUID。

    """
    # 主键，使用 UUID 字符串表示
    id: Mapped[str] = mapped_column(primary_key=True, default=lambda _: str(uuid4()))

    # JSON 类型字段的类型映射
    type_annotation_map = {
        list[dict]: JSON,
        list[str]: JSON,
        dict: JSON,
    }
    # 统一的 MetaData 对象，用于所有继承自 BaseTable 的模型
    metadata = MetaData(
        # Naming conventions for constraints, foreign keys, etc.
        # ix: Index
        # uq: Unique constraint
        # ck: Check constraint
        # fk: Foreign key
        # pk: Primary key
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_`%(constraint_name)s`",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )

    def __repr__(self) -> str:
        """ 返回模型实例的字符串表示，用于调试和日志记录。包含所有列的属性=值对。"""
        # 获取所有列并生成属性=值对
        column_values = {
            prop.key: getattr(self, prop.key)
            for prop in self.__mapper__.iterate_properties
            if isinstance(prop, ColumnProperty)
        }

        # 格式化为字符串
        columns_repr = ", ".join(f"{key}={value}" for key, value in column_values.items())
        return f"<{self.__class__.__name__}({columns_repr})>"

    @classmethod
    async def get_by_id(cls, session: "AsyncSession", tid: str) -> Optional[Self]:
        """根据 UUID 主键获取单个记录。"""
        if not isinstance(tid, UUID):
            tid = UUID(tid)
        # 通过 SQLAlchemy 的 select 语句查询记录
        result = await session.execute(select(cls).where(cls.id == tid))
        # 返回查询结果中的单个记录或 None
        return result.scalar_one_or_none()

    @classmethod
    async def delete_by_id(cls, session: "AsyncSession", tid: str) -> int:
        if not isinstance(tid, UUID):
            tid = UUID(tid)
        result = await session.execute(delete(cls).where(cls.id == tid))
        await session.commit()
        return result.rowcount()
