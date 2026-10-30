from collections.abc import Callable, Iterable, Iterator
from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Date, DateTime, MetaData, create_engine, select
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# All timestamps are naive UTC with microsecond precision.
UtcDateTime = DateTime().with_variant(DATETIME(fsp=6), "mysql")


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map = {
        datetime: UtcDateTime,
        date: Date,
        dict[str, Any]: JSON,
        list[Any]: JSON,
    }


_engine = None
_session_factory: sessionmaker[Session] | None = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True, pool_recycle=3600)
    return _engine


def session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _session_factory


def reset_engine() -> None:
    """Drop the cached engine, used by tests after changing settings."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def get_db() -> Iterator[Session]:
    db = session_factory()()
    try:
        yield db
    finally:
        db.close()


def preload(db: Session, model: Any, ids: Iterable[int | None]) -> None:
    """Load these rows in one query, so later db.get() calls for them need none.

    Lists use it before building each row, instead of fetching every related record one at a
    time (section 15: list queries under 300 ms at design scale).
    """
    wanted = {i for i in ids if i is not None}
    missing = [i for i in wanted if db.identity_map.get(db.identity_key(model, i)) is None]
    # The session only holds rows weakly; keep these until it closes, or they are dropped at once.
    kept = db.info.setdefault("preloaded", [])
    for start in range(0, len(missing), 1000):
        kept.extend(db.execute(select(model).where(model.id.in_(missing[start : start + 1000]))).scalars())


def per_session(db: Session, key: str, load: Callable[[], Any]) -> Any:
    """A value worked out once per session (one request), such as the district row."""
    cache = db.info.setdefault("cached", {})
    if key not in cache:
        value = load()
        if value is None:
            return None
        cache[key] = value
    return cache[key]
