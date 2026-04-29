"""SQLAlchemy engine 与 session 管理。

Engine 为模块级单例，内置连接池复用，所有数据库操作共用一个 engine。
Session 使用 scoped_session 保证线程安全（Streamlit 多线程访问）。
"""

from sqlalchemy.orm.session import Session


from sqlalchemy.orm.session import Session


from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, scoped_session, sessionmaker

_engine: Engine | None = None
_SessionFactory: scoped_session | None = None


def init_engine(database_url: str, echo: bool = False) -> Engine:
    """初始化全局 Engine（启动时调用一次）。

    Args:
        database_url: SQLAlchemy 连接 URL，如 postgresql://user:pass@host:port/db
        echo:        是否打印 SQL 日志，调试时可开启

    Returns:
        初始化后的 Engine 实例
    """
    global _engine, _SessionFactory
    _engine = create_engine(
        database_url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,   # 每次从池中取连接前先 ping，避免用到已断开的连接
        echo=echo,
    )
    _SessionFactory = scoped_session[Session](sessionmaker[Session](bind=_engine))
    return _engine


def get_session() -> Session:
    """获取线程安全的数据库会话。

    每次调用返回当前线程绑定的 session，同一线程多次调用返回同一 session。
    Runner / Fetcher / Dashboard 统一使用此方法获取 session。

    Returns:
        当前线程绑定的 SQLAlchemy Session

    Raises:
        RuntimeError: Engine 未初始化时抛出
    """
    if _SessionFactory is None:
        raise RuntimeError("Engine 未初始化，请先调用 init_engine()")
    return _SessionFactory()


def dispose_engine() -> None:
    """关闭 Engine 和所有连接池连接（应用退出时调用）。"""
    global _engine, _SessionFactory
    if _SessionFactory is not None:
        _SessionFactory.remove()
        _SessionFactory = None
    if _engine is not None:
        _engine.dispose()
        _engine = None
