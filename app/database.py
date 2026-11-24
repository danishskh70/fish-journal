import warnings

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import settings

# SQLite stores Numeric as float; values are re-quantised on read. Postgres is exact.
warnings.filterwarnings("ignore", message=".*support Decimal objects natively.*")


class Base(DeclarativeBase):
    pass


def normalise_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url

def make_engine(url: str):
    url = normalise_url(url)
    if url.startswith("sqlite"):
        kwargs = {"connect_args": {"check_same_thread": False}}
        if url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool
        engine = create_engine(url, **kwargs)

        @event.listens_for(engine, "connect")
        def _fk(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        return engine
    return create_engine(url, pool_pre_ping=True)


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
