"""DB ulanishlari: API uchun async, Celery ishchilari uchun sync sessiya."""
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

_settings = get_settings()

async_engine = create_async_engine(_settings.database_url, pool_pre_ping=True, pool_size=10)
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False)

sync_engine = create_engine(_settings.database_url, pool_pre_ping=True, pool_size=5)
SyncSessionLocal = sessionmaker(sync_engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session


@contextmanager
def sync_session() -> Iterator[Session]:
    session = SyncSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
