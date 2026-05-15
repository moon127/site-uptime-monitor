import json
from datetime import datetime, timezone
from sqlalchemy import text


# ── Dashboard ──────────────────────────────────────────────────────────

def test_dashboard_returns_200(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Site Status Monitor" in r.text


def test_dashboard_shows_sites(client):
    r = client.get("/")
    assert "google.com" in r.text
    assert "github.com" in r.text
    assert "ubuntu.com" in r.text


def test_dashboard_period_param(client):
    for period in ("hourly", "daily", "monthly"):
        r = client.get(f"/?period={period}")
        assert r.status_code == 200


def test_dashboard_contains_chart_data(client):
    r = client.get("/")
    assert "chartData" in r.text or "chart_data" in r.text


# ── Admin setup / login / logout ───────────────────────────────────────

def test_admin_setup_creates_user(client, db):
    from app.models import AdminUser
    r = client.post("/admin/setup", data={"password": "secret99"})
    assert r.status_code == 303
    assert db.query(AdminUser).count() == 1


def test_admin_setup_rejects_short_password(client):
    r = client.post("/admin/setup", data={"password": "ab"})
    assert r.status_code == 400


def test_admin_login_returns_page(client):
    client.post("/admin/setup", data={"password": "test123"}, follow_redirects=False)
    client.cookies.clear()
    r = client.get("/admin/login")
    assert r.status_code == 200
    assert "password" in r.text.lower()


def test_admin_login_bad_password(client):
    client.post("/admin/setup", data={"password": "test123"})
    r = client.post("/admin/login", data={"password": "wrong"})
    assert r.status_code == 401


def test_admin_login_success(client):
    client.post("/admin/setup", data={"password": "test123"})
    r = client.post("/admin/login", data={"password": "test123"}, follow_redirects=False)
    assert r.status_code == 303


def test_admin_logout(client):
    client.post("/admin/setup", data={"password": "test123"})
    r = client.post("/admin/logout", follow_redirects=False)
    assert r.status_code == 303


# ── Admin dashboard ────────────────────────────────────────────────────

def test_admin_index_redirects_when_not_logged_in(client):
    r = client.get("/admin", follow_redirects=False)
    assert r.status_code == 303


def test_admin_index_shows_stats(admin_client):
    r = admin_client.get("/admin")
    assert r.status_code == 200
    assert "Statistics" in r.text
    assert "Total Checks" in r.text


def test_admin_index_shows_orgs_and_sites(admin_client):
    r = admin_client.get("/admin")
    assert "misc" in r.text
    assert "google" in r.text


# ── Manage orgs ────────────────────────────────────────────────────────

def test_add_org(admin_client, db):
    from app.models import Org
    r = admin_client.post("/admin/org/add", data={"org_name": "neworg"})
    assert r.status_code == 303
    assert db.query(Org).filter(Org.name == "neworg").count() == 1


def test_add_org_with_site(admin_client, db):
    from app.models import Org, Site
    r = admin_client.post("/admin/org/add", data={
        "org_name": "testorg", "site_name": "testsite", "url": "https://example.com"
    })
    assert r.status_code == 303
    assert db.query(Org).filter(Org.name == "testorg").count() == 1
    assert db.query(Site).filter(Site.name == "testsite").count() == 1


def test_add_duplicate_org(admin_client):
    r = admin_client.post("/admin/org/add", data={"org_name": "misc"})
    assert r.status_code == 400


def test_delete_org(admin_client, db):
    from app.models import Org
    r = admin_client.post("/admin/org/delete", data={"org_name": "misc"})
    assert r.status_code == 303
    assert db.query(Org).filter(Org.name == "misc").count() == 0


# ── Manage sites ───────────────────────────────────────────────────────

def test_add_site(admin_client, db):
    from app.models import Site
    r = admin_client.post("/admin/site/add", data={
        "org_name": "misc", "site_name": "new-site", "url": "https://new.example.com"
    })
    assert r.status_code == 303
    assert db.query(Site).filter(Site.name == "new-site").count() == 1


def test_delete_site(admin_client, db):
    from app.models import Site
    r = admin_client.post("/admin/site/delete", data={"site_name": "google"})
    assert r.status_code == 303
    assert db.query(Site).filter(Site.name == "google").count() == 0


# ── Rename org (historical data preserved) ─────────────────────────────

def test_rename_org(admin_client, db):
    from app.models import Org, Site
    # Grab the current site count and IDs before rename
    sites_before = {s.name: s.id for s in db.query(Site).all()}

    r = admin_client.post("/admin/org/rename", data={
        "org_name": "misc", "new_name": "renamed-org"
    })
    assert r.status_code == 303

    # Org name changed
    assert db.query(Org).filter(Org.name == "renamed-org").count() == 1
    assert db.query(Org).filter(Org.name == "misc").count() == 0

    # Site IDs unchanged
    sites_after = {s.name: s.id for s in db.query(Site).all()}
    # Sites should have same IDs as before (just org_id still points to same org)
    google = db.query(Site).filter(Site.name == "google").first()
    assert google is not None
    assert google.id == sites_before["google"]


def test_rename_org_updates_config(admin_client):
    # Rename back to original for test isolation
    admin_client.post("/admin/org/rename", data={
        "org_name": "misc", "new_name": "temp-rename"
    })
    from app.config import config
    assert "temp-rename" in config.orgs
    assert "misc" not in config.orgs

    # Restore for other tests
    admin_client.post("/admin/org/rename", data={
        "org_name": "temp-rename", "new_name": "misc"
    })
    assert "misc" in config.orgs


# ── Rename site (historical data preserved) ────────────────────────────

def test_rename_site(admin_client, db):
    from app.models import Site
    site_before = db.query(Site).filter(Site.name == "google").first()
    assert site_before is not None
    old_id = site_before.id
    old_org_id = site_before.org_id

    r = admin_client.post("/admin/site/rename", data={
        "site_name": "google", "new_name": "renamed-site"
    })
    assert r.status_code == 303

    renamed = db.query(Site).filter(Site.name == "renamed-site").first()
    assert renamed is not None
    assert renamed.id == old_id       # Stable ID
    assert renamed.org_id == old_org_id  # Org membership preserved
    assert db.query(Site).filter(Site.name == "google").count() == 0


def test_rename_site_updates_config(admin_client):
    admin_client.post("/admin/site/rename", data={
        "site_name": "google", "new_name": "google-renamed"
    })
    from app.config import config
    assert "google-renamed" in config.sites
    assert "google" not in config.sites

    admin_client.post("/admin/site/rename", data={
        "site_name": "google-renamed", "new_name": "google"
    })


# ── Status management ──────────────────────────────────────────────────

def test_set_org_status(admin_client, db):
    from app.models import SiteStatus
    r = admin_client.post("/admin/status/set", data={
        "scope": "org", "scope_name": "misc",
        "status_type": "degraded", "message": "testing"
    })
    assert r.status_code == 303
    active = db.query(SiteStatus).filter(
        SiteStatus.active == True, SiteStatus.scope == "org"
    ).all()
    assert len(active) == 1
    assert active[0].message == "testing"


def test_set_site_status(admin_client, db):
    from app.models import SiteStatus
    r = admin_client.post("/admin/status/set", data={
        "scope": "site", "scope_name": "google",
        "status_type": "maintenance", "message": "down for maintenance"
    })
    assert r.status_code == 303
    active = db.query(SiteStatus).filter(
        SiteStatus.active == True, SiteStatus.scope == "site"
    ).all()
    assert len(active) == 1


def test_set_status_deactivates_old(admin_client, db):
    from app.models import SiteStatus, Org
    admin_client.post("/admin/status/set", data={
        "scope": "org", "scope_name": "misc",
        "status_type": "degraded", "message": "first"
    })
    admin_client.post("/admin/status/set", data={
        "scope": "org", "scope_name": "misc",
        "status_type": "maintenance", "message": "second"
    })
    org = db.query(Org).filter(Org.name == "misc").first()
    active = db.query(SiteStatus).filter(
        SiteStatus.active == True, SiteStatus.scope == "org",
        SiteStatus.scope_id == org.id
    ).all()
    assert len(active) == 1
    assert active[0].message == "second"


def test_status_update_appends_to_updates(admin_client, db):
    from app.models import SiteStatus
    admin_client.post("/admin/status/set", data={
        "scope": "org", "scope_name": "misc",
        "status_type": "degraded", "message": "original"
    })
    status = db.query(SiteStatus).filter(
        SiteStatus.active == True, SiteStatus.scope == "org"
    ).first()
    r = admin_client.post("/admin/status/update", data={
        "status_id": status.id, "message": "updated message"
    })
    assert r.status_code == 303
    db.refresh(status)
    assert status.message == "updated message"
    import json
    updates = json.loads(status.updates)
    assert len(updates) == 1
    assert updates[0]["message"] == "original"


def test_clear_status(admin_client, db):
    from app.models import SiteStatus
    admin_client.post("/admin/status/set", data={
        "scope": "org", "scope_name": "misc",
        "status_type": "degraded", "message": "to-clear"
    })
    status = db.query(SiteStatus).filter(
        SiteStatus.active == True, SiteStatus.scope == "org"
    ).first()
    r = admin_client.post("/admin/status/clear", data={"status_id": status.id})
    assert r.status_code == 303
    db.refresh(status)
    assert status.active == False
    assert status.ended_at is not None


def test_status_history_appears_on_admin(admin_client):
    admin_client.post("/admin/status/set", data={
        "scope": "org", "scope_name": "misc",
        "status_type": "degraded", "message": "history test"
    })
    r = admin_client.get("/admin")
    assert "history test" in r.text
    assert "degraded" in r.text


def test_status_survives_org_rename(admin_client, db):
    from app.models import SiteStatus
    admin_client.post("/admin/status/set", data={
        "scope": "org", "scope_name": "misc",
        "status_type": "degraded", "message": "pre-rename"
    })
    admin_client.post("/admin/org/rename", data={
        "org_name": "misc", "new_name": "misc-renamed"
    })
    active = db.query(SiteStatus).filter(
        SiteStatus.active == True, SiteStatus.scope == "org"
    ).all()
    assert len(active) == 1
    assert active[0].message == "pre-rename"

    # Dashboard should show status under new name
    r = admin_client.get("/")
    assert "misc-renamed" in r.text
    assert "pre-rename" in r.text

    # Restore
    admin_client.post("/admin/org/rename", data={
        "org_name": "misc-renamed", "new_name": "misc"
    })


# ── Uptime % in dashboard ──────────────────────────────────────────────

def test_uptime_column_in_dashboard(admin_client, db):
    from app.models import CheckResult, Site
    site = db.query(Site).filter(Site.name == "google").first()
    now = datetime.now(timezone.utc)
    db.add_all([
        CheckResult(site_id=site.id, url="https://google.com",
                    timestamp=now, status_code=200, response_time_ms=10.0, is_up=True),
        CheckResult(site_id=site.id, url="https://google.com",
                    timestamp=now, status_code=500, response_time_ms=10.0, is_up=False),
        CheckResult(site_id=site.id, url="https://google.com",
                    timestamp=now, status_code=200, response_time_ms=10.0, is_up=True),
    ])
    db.commit()
    r = admin_client.get("/admin")
    assert "66.7%" in r.text or "66.67%" in r.text
