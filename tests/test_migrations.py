import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app.database import Base


def test_alembic_upgrade_creates_exactly_the_model_schema(tmp_path):
    url = f"sqlite:///{tmp_path / 'mig.db'}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    insp = sa.inspect(sa.create_engine(url))
    tables = set(insp.get_table_names()) - {"alembic_version"}
    assert tables == set(Base.metadata.tables)
    for t in Base.metadata.tables.values():
        assert {c["name"] for c in insp.get_columns(t.name)} == {c.name for c in t.columns}, t.name
    command.downgrade(cfg, "base")
    assert set(sa.inspect(sa.create_engine(url)).get_table_names()) == {"alembic_version"}
