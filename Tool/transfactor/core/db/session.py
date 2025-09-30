import asyncio
import warnings
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession

from core.logger.runtime import get_logger

class SessionManager:
    """
    Attributes:
        url (str): 默认数据库 URL
        debug_sql (bool): 是否开启 SQL 调试模式
    """

    url: str
    debug_sql: bool

    def __init__(self, url: str, debug_sql: bool = False):
        self.logger = get_logger(name="DBSessionManager", filename="db_session_manager.log")
        self.url = url
        self.debug_sql = debug_sql
        # 创建异步数据库引擎，用于连接数据库
        self.engine = create_async_engine(
            url=url,
            echo=debug_sql,
        )
        # async_sessionmaker 用于创建异步会话工厂
        # 这里设置 expire_on_commit=False，防止提交后对象被过期，避免再次访问时需要重新加载
        self.session_class = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
            class_=AsyncSession
        )
        self.session = None
        self.recursion_depth = 0

        # 监听数据库连接事件，当连接建立时执行 _on_connect
        event.listen(self.engine.sync_engine, "connect", self._on_connect)

    def _on_connect(self, dbapi_connection, _):
        """数据库连接事件回调。
        对 sqlite 数据库开启外键支持。
        Args:
            dbapi_connection: 数据库连接对象，例如 sqlite3.Connection
            _: 连接记录（未使用）
        """
        if self.url.startswith("sqlite"):
            # 注意 SQLite 默认使用 NullPool，这意味着每个会话都会创建一个数据库“连接”。
            # 这对于 SQLite 来说是可以的，因为它是一个本地文件。
            # PostgreSQL 或其他数据库默认使用真正的连接池。
            dbapi_connection.execute("pragma foreign_keys=on")

    async def astart(self) -> AsyncSession:
        """获取数据库会话对象。
        如果已经存在会话对象，则直接返回，否则创建新的会话对象。
        """
        if self.session is not None:
            self.recursion_depth += 1
            self.logger.warning(
                f"Re-entering database session (depth: {self.recursion_depth}), potential bug",
                stack_info=True
            )
            return self.session

        self.session = self.session_class()
        return self.session

    async def aclose(self):
        """关闭数据库会话对象。
        如果存在会话对象，则关闭会话对象。
        """
        if self.session is None:
            self.logger.warning(
                "Closing non-existing database session, potential bug",
                stack_info=True
            )
            return

        if self.recursion_depth > 0:
            self.recursion_depth -= 1
            return

        await self.session.close()
        self.session = None

    async def __aenter__(self):
        return await self.astart()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return await self.aclose()
