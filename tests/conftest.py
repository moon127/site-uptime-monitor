import os
import sys
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# --- Monkey-patch database BEFORE any test module imports app ---
_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TEST_DB_PATH = _db.name
_db.close()

import app.database as db_mod

db_mod.DB_PATH = Path(TEST_DB_PATH)
db_mod.DATABASE_URL = f"sqlite:///{TEST_DB_PATH}"
db_mod.engine = create_engine(
    db_mod.DATABASE_URL, connect_args={"check_same_thread": False}
)
db_mod.SessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=db_mod.engine
)

# Now safe to import the app (migrations will use the patched URL)
from app.main import app as _app
from app.config import config as _config, CONFIG_PATH

# Save original config so we can restore it after tests
_ORIGINAL_CONFIG = CONFIG_PATH.read_text() if CONFIG_PATH.exists() else ""

# Write a known test config so tests are deterministic regardless of user's config
_TEST_CONFIG = """\
[org:ubuntu]
ubuntu = https://ubuntu.com

[org:misc]
google = https://google.com
github = https://github.com

[settings]
retention_days = 90
poll_interval = 60
"""
CONFIG_PATH.write_text(_TEST_CONFIG)
_config._load()


@pytest.fixture(scope="session", autouse=True)
def _cleanup():
    yield
    os.unlink(TEST_DB_PATH)
    CONFIG_PATH.write_text(_ORIGINAL_CONFIG)


@pytest.fixture(autouse=True)
def _clean_tables():
    """Wipe dynamic data between tests but keep schema intact."""
    from app.database import engine as _engine
    with _engine.connect() as conn:
        for t in ("site_status", "check_results", "sites", "orgs", "admin_user"):
            conn.execute(text(f"DELETE FROM {t}"))
        conn.commit()
    # Restore config from the hardcoded test config to undo any in-memory mutations
    CONFIG_PATH.write_text(_TEST_CONFIG)
    _config._load()
    _config._sync_db()


@pytest.fixture
def client():
    from starlette.testclient import TestClient
    with TestClient(_app, follow_redirects=False) as c:
        yield c


@pytest.fixture
def admin_client(client):
    """Client with an active admin session."""
    r = client.post("/admin/setup", data={"password": "test123"})
    assert r.status_code == 303
    return client


@pytest.fixture
def db():
    from app.database import SessionLocal
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
