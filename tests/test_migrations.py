import os
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker


def test_alembic_version_table_exists(db):
    """After startup migrations, alembic_version should exist."""
    from app.database import engine
    with engine.connect() as conn:
        result = conn.execute(text("SELECT version_num FROM alembic_version"))
        version = result.scalar()
        assert version is not None
        assert len(version) > 0


def test_alembic_is_at_head(db):
    """The applied revision should be the initial (only) migration."""
    from app.database import engine
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    app_dir = Path(__file__).resolve().parent.parent
    cfg = Config(str(app_dir / "alembic.ini"))
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()

    with engine.connect() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()

    assert current == head, f"DB at {current}, head is {head}"


def test_migration_creates_all_tables(db):
    """Verify all expected tables exist after migration."""
    from app.database import engine
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    expected = {"orgs", "sites", "check_results", "site_status", "admin_user", "alembic_version"}
    assert expected.issubset(tables), f"Missing: {expected - tables}"


def test_migration_on_blank_database():
    """Alembic can bootstrap a completely empty database from scratch."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = tmp.name
    tmp.close()

    try:
        engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

        from alembic.config import Config
        from alembic.command import upgrade
        app_dir = Path(__file__).resolve().parent.parent
        cfg = Config(str(app_dir / "alembic.ini"))
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
        upgrade(cfg, "head")

        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert "orgs" in tables
        assert "sites" in tables
        assert "check_results" in tables
        assert "site_status" in tables
        assert "alembic_version" in tables

        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert version is not None
    finally:
        engine.dispose()
        os.unlink(db_path)


def test_migration_idempotent():
    """Running upgrade twice should not error (already at head)."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = tmp.name
    tmp.close()

    try:
        engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

        from alembic.config import Config
        from alembic.command import upgrade
        app_dir = Path(__file__).resolve().parent.parent
        cfg = Config(str(app_dir / "alembic.ini"))
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

        upgrade(cfg, "head")
        upgrade(cfg, "head")  # second run should be a no-op

        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert "orgs" in tables
    finally:
        engine.dispose()
        os.unlink(db_path)
