from app.config import config


def test_config_loads_sites():
    assert len(config.sites) >= 1
    assert "google" in config.sites


def test_config_loads_orgs():
    assert len(config.orgs) >= 1
    assert "misc" in config.orgs
    assert "google" in config.orgs["misc"]


def test_config_settings():
    assert config.retention_days >= 1
    assert config.poll_interval >= 1


def test_sync_db_creates_org_records(db):
    from app.models import Org
    orgs = db.query(Org).all()
    names = {o.name for o in orgs}
    assert "misc" in names


def test_sync_db_creates_site_records(db):
    from app.models import Site
    sites = db.query(Site).all()
    names = {s.name for s in sites}
    assert "google" in names


def test_sync_db_sets_org_id_on_sites(db):
    from app.models import Org, Site
    misc = db.query(Org).filter(Org.name == "misc").first()
    assert misc is not None
    google = db.query(Site).filter(Site.name == "google").first()
    assert google is not None
    assert google.org_id == misc.id
