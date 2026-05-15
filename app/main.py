import hashlib
import json
import secrets
import base64
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, cast, Integer
from starlette.middleware.sessions import SessionMiddleware

from app.database import engine, SessionLocal
from app.models import Base, CheckResult, AdminUser, SiteStatus, Org, Site
from app.config import config
from app.monitor import SiteMonitor


def run_migrations():
    from alembic.config import Config
    from alembic.command import upgrade
    from pathlib import Path
    from app.database import DATABASE_URL
    alembic_ini = Path(__file__).resolve().parent.parent / "alembic.ini"
    cfg = Config(str(alembic_ini))
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    upgrade(cfg, "head")


run_migrations()
config._sync_db()
templates = Jinja2Templates(directory="app/templates")
monitor = SiteMonitor()


def bucket_records(records, bucket_fmt, label_fmt):
    buckets: dict = defaultdict(lambda: {"count": 0, "up": 0, "total_ms": 0.0})
    label_cache: dict[str, str] = {}

    for r in records:
        key = r.timestamp.strftime(bucket_fmt)
        if key not in label_cache:
            label_cache[key] = r.timestamp.strftime(label_fmt)
        buckets[key]["count"] += 1
        if r.is_up:
            buckets[key]["up"] += 1
        buckets[key]["total_ms"] += r.response_time_ms

    sorted_keys = sorted(buckets.keys())
    return {
        "timestamps": [label_cache[k] for k in sorted_keys],
        "uptime": [
            round((buckets[k]["up"] / buckets[k]["count"]) * 100, 1)
            for k in sorted_keys
        ],
        "response_time": [
            round(buckets[k]["total_ms"] / buckets[k]["count"], 2)
            for k in sorted_keys
        ],
    }


def _hash_password(password: str) -> tuple[str, str]:
    salt = secrets.token_hex(32)
    key = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt.encode("utf-8"),
        n=16384, r=8, p=1, dklen=64,
    )
    return base64.b64encode(key).decode("utf-8"), salt


def _verify_password(password: str, stored_hash: str, salt: str) -> bool:
    key = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt.encode("utf-8"),
        n=16384, r=8, p=1, dklen=64,
    )
    return secrets.compare_digest(
        base64.b64encode(key).decode("utf-8"), stored_hash
    )


def _admin_exists() -> bool:
    db = SessionLocal()
    try:
        return db.query(AdminUser).first() is not None
    finally:
        db.close()


def _check_admin(request: Request) -> bool:
    return bool(request.session.get("admin"))


def _status_to_dict(s):
    d = {
        "id": s.id,
        "scope": s.scope,
        "scope_name": '',
        "scope_id": s.scope_id,
        "status_type": s.status_type,
        "message": s.message,
        "active": s.active,
        "created_at": s.created_at,
        "ended_at": s.ended_at,
        "updates": json.loads(s.updates) if s.updates else [],
    }
    return d


def _get_active_statuses(db):
    active = db.query(SiteStatus).filter(SiteStatus.active == True).all()
    orgs = {}
    sites = {}
    for s in active:
        current_name = _get_current_scope_name(db, s.scope, s.scope_id)
        entry = {"type": s.status_type, "message": s.message, "updates": json.loads(s.updates) if s.updates else []}
        if s.scope == "org":
            orgs[current_name] = entry
        else:
            sites[current_name] = entry
    return orgs, sites


def _get_current_scope_name(db, scope, scope_id):
    if scope == "org":
        org = db.query(Org).filter(Org.id == scope_id).first()
        return org.name if org else str(scope_id)
    else:
        site = db.query(Site).filter(Site.id == scope_id).first()
        return site.name if site else str(scope_id)


def _lookup_site_id(db, name):
    site = db.query(Site).filter(Site.name == name).first()
    return site.id if site else None


def _lookup_org_id(db, name):
    org = db.query(Org).filter(Org.name == name).first()
    return org.id if org else None


@asynccontextmanager
async def lifespan(app: FastAPI):
    SiteMonitor.prune_old_data()
    monitor.start()
    yield
    if monitor._task:
        monitor._task.cancel()


app = FastAPI(title="Site Monitor", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=secrets.token_hex(32))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, period: str = "hourly"):
    if config.check_and_reload():
        SiteMonitor.prune_old_data()

    now = datetime.now(timezone.utc)
    period_map = {
        "hourly": timedelta(hours=1),
        "daily": timedelta(days=1),
        "monthly": timedelta(days=30),
    }
    delta = period_map.get(period, timedelta(hours=1))
    if period not in period_map:
        period = "hourly"
    cutoff = now - delta

    bucket_config = {
        "hourly": ("%Y%m%d%H%M", "%H:%M"),
        "daily": ("%Y%m%d%H", "%a %H:00"),
        "monthly": ("%Y%m%d", "%b %d"),
    }
    bfmt, lfmt = bucket_config[period]

    db = SessionLocal()
    try:
        org_statuses, site_statuses = _get_active_statuses(db)
        sites_data = []
        chart_data = {}

        for name, url in config.sites.items():
            site_id = _lookup_site_id(db, name)
            if not site_id:
                continue

            latest = (
                db.query(CheckResult)
                .filter(CheckResult.site_id == site_id)
                .order_by(CheckResult.timestamp.desc())
                .first()
            )

            stats = (
                db.query(
                    func.min(CheckResult.response_time_ms).label("min_ms"),
                    func.max(CheckResult.response_time_ms).label("max_ms"),
                    func.avg(CheckResult.response_time_ms).label("avg_ms"),
                    func.avg(cast(CheckResult.is_up, Integer)).label("uptime_pct"),
                )
                .filter(
                    CheckResult.site_id == site_id,
                    CheckResult.timestamp >= cutoff,
                )
                .first()
            )

            def _fmt(v):
                return round(v, 2) if v is not None else "N/A"

            display_name = urlparse(url).netloc

            sites_data.append(
                {
                    "name": name,
                    "display_name": display_name,
                    "url": url,
                    "status": "UP" if latest and latest.is_up else "DOWN",
                    "uptime_pct": f"{round(stats.uptime_pct * 100, 1)}%" if stats.uptime_pct is not None else "N/A",
                    "current_ms": (
                        _fmt(latest.response_time_ms) if latest else "N/A"
                    ),
                    "min_ms": _fmt(stats.min_ms),
                    "max_ms": _fmt(stats.max_ms),
                    "avg_ms": _fmt(stats.avg_ms),
                    "manual_status": site_statuses.get(name),
                }
            )

            records = (
                db.query(CheckResult)
                .filter(
                    CheckResult.site_id == site_id,
                    CheckResult.timestamp >= cutoff,
                )
                .order_by(CheckResult.timestamp)
                .all()
            )

            chart_data[name] = bucket_records(records, bfmt, lfmt)
    finally:
        db.close()

    if config.orgs:
        orgs_list = []
        for org_name, org_sites in config.orgs.items():
            entries = [sd for sd in sites_data if sd["name"] in org_sites]
            orgs_list.append({
                "name": org_name,
                "sites": entries,
                "status": org_statuses.get(org_name),
            })
    else:
        orgs_list = [{"name": "All Sites", "sites": sites_data}]

    site_display_names = {
        name: urlparse(url).netloc for name, url in config.sites.items()
    }

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "sites": sites_data,
            "orgs": orgs_list,
            "chart_data": json.dumps(chart_data),
            "period": period,
            "site_names": json.dumps(list(config.sites.keys())),
            "site_display_names": json.dumps(site_display_names),
            "poll_interval": config.poll_interval,
            "admin_exists": _admin_exists(),
        },
    )


@app.get("/admin", response_class=HTMLResponse)
async def admin_index(request: Request):
    if not _admin_exists():
        return RedirectResponse("/admin/setup", status_code=303)
    if not _check_admin(request):
        return RedirectResponse("/admin/login", status_code=303)

    db = SessionLocal()
    try:
        total_checks = db.query(func.count(CheckResult.id)).scalar()
        total_up = (
            db.query(func.count(CheckResult.id))
            .filter(CheckResult.is_up == True)
            .scalar()
        )
        total_down = (
            db.query(func.count(CheckResult.id))
            .filter(CheckResult.is_up == False)
            .scalar()
        )

        per_site_raw = (
            db.query(
                CheckResult.site_id,
                func.count(CheckResult.id).label("total"),
            )
            .group_by(CheckResult.site_id)
            .all()
        )
        per_site_up = (
            db.query(
                CheckResult.site_id,
                func.count(CheckResult.id).label("up_count"),
            )
            .filter(CheckResult.is_up == True)
            .group_by(CheckResult.site_id)
            .all()
        )

        active_status_list_raw = (
            db.query(SiteStatus)
            .filter(SiteStatus.active == True)
            .order_by(SiteStatus.created_at.desc())
            .all()
        )
        status_history_raw = (
            db.query(SiteStatus)
            .order_by(SiteStatus.created_at.desc())
            .limit(100)
            .all()
        )

        up_map = {r.site_id: r.up_count for r in per_site_up}
        site_stats = []
        for r in per_site_raw:
            site_obj = db.query(Site).filter(Site.id == r.site_id).first()
            name = site_obj.name if site_obj else f"unknown-{r.site_id}"
            site_stats.append({
                "name": name,
                "total": r.total,
                "up": up_map.get(r.site_id, 0),
                "down": r.total - up_map.get(r.site_id, 0),
            })
        site_stats.sort(key=lambda s: s["name"])

        active_statuses = []
        for s in active_status_list_raw:
            d = _status_to_dict(s)
            d["scope_name"] = _get_current_scope_name(db, s.scope, s.scope_id)
            active_statuses.append(d)

        status_history = []
        for s in status_history_raw:
            d = _status_to_dict(s)
            d["scope_name"] = _get_current_scope_name(db, s.scope, s.scope_id)
            status_history.append(d)
    finally:
        db.close()

    orgs_for_admin = []
    if config.orgs:
        for org_name, org_sites in config.orgs.items():
            entries = [
                {"name": sname, "url": url}
                for sname, url in org_sites.items()
            ]
            orgs_for_admin.append({"name": org_name, "sites": entries})
    else:
        entries = [
            {"name": sname, "url": url}
            for sname, url in config.sites.items()
        ]
        orgs_for_admin.append({"name": "All Sites", "sites": entries})

    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "total_checks": total_checks,
            "total_up": total_up or 0,
            "total_down": total_down or 0,
            "total_sites": len(config.sites),
            "total_orgs": len(config.orgs) if config.orgs else 1,
            "site_stats": site_stats,
            "orgs": orgs_for_admin,
            "active_statuses": active_statuses,
            "status_history": status_history,
            "org_names": list(config.orgs.keys()) if config.orgs else [],
            "site_names": list(config.sites.keys()),
        },
    )


@app.get("/admin/setup", response_class=HTMLResponse)
async def admin_setup(request: Request):
    if _admin_exists():
        return RedirectResponse("/admin/login", status_code=303)
    return templates.TemplateResponse(request, "admin_setup.html", {})


@app.post("/admin/setup")
async def admin_setup_post(request: Request, password: str = Form(...)):
    if _admin_exists():
        raise HTTPException(status_code=400, detail="Admin already exists")

    if len(password) < 6:
        return templates.TemplateResponse(
            request, "admin_setup.html", {"error": "Password must be at least 6 characters"},
            status_code=400,
        )

    pw_hash, salt = _hash_password(password)
    db = SessionLocal()
    try:
        db.add(AdminUser(password_hash=pw_hash, salt=salt))
        db.commit()
    finally:
        db.close()

    request.session["admin"] = True
    return RedirectResponse("/admin", status_code=303)


@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login(request: Request):
    if _check_admin(request):
        return RedirectResponse("/admin", status_code=303)
    if not _admin_exists():
        return RedirectResponse("/admin/setup", status_code=303)
    return templates.TemplateResponse(request, "admin_login.html", {})


@app.post("/admin/login")
async def admin_login_post(request: Request, password: str = Form(...)):
    db = SessionLocal()
    try:
        user = db.query(AdminUser).first()
        if user is None:
            return RedirectResponse("/admin/setup", status_code=303)
        if not _verify_password(password, user.password_hash, user.salt):
            return templates.TemplateResponse(
                request, "admin_login.html", {"error": "Incorrect password"},
                status_code=401,
            )
    finally:
        db.close()

    request.session["admin"] = True
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/logout")
async def admin_logout(request: Request):
    request.session["admin"] = False
    return RedirectResponse("/", status_code=303)


@app.post("/admin/org/add")
async def admin_org_add(
    request: Request,
    org_name: str = Form(...),
    site_name: str = Form(default=""),
    url: str = Form(default=""),
):
    if not _check_admin(request):
        raise HTTPException(status_code=401)

    org_name = org_name.strip()
    if not org_name:
        raise HTTPException(status_code=400, detail="Org name is required")

    if org_name in config.orgs:
        raise HTTPException(status_code=400, detail="Org already exists")

    config.orgs[org_name] = {}
    if site_name and url:
        config.orgs[org_name][site_name.strip()] = url.strip()
        config.sites[site_name.strip()] = url.strip()

    config.save()
    config._sync_db()
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/org/delete")
async def admin_org_delete(request: Request, org_name: str = Form(...)):
    if not _check_admin(request):
        raise HTTPException(status_code=401)

    if org_name not in config.orgs:
        raise HTTPException(status_code=400, detail="Org not found")

    for sname in config.orgs[org_name]:
        config.sites.pop(sname, None)
    del config.orgs[org_name]
    config.save()
    config._sync_db()
    SiteMonitor.prune_old_data()
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/org/rename")
async def admin_org_rename(
    request: Request,
    org_name: str = Form(...),
    new_name: str = Form(...),
):
    if not _check_admin(request):
        raise HTTPException(status_code=401)

    org_name = org_name.strip()
    new_name = new_name.strip()
    if not org_name or not new_name:
        raise HTTPException(status_code=400, detail="Both names are required")
    if org_name not in config.orgs:
        raise HTTPException(status_code=400, detail="Org not found")
    if new_name == org_name:
        return RedirectResponse("/admin", status_code=303)

    config.orgs[new_name] = config.orgs.pop(org_name)

    db = SessionLocal()
    try:
        org = db.query(Org).filter(Org.name == org_name).first()
        if org:
            org.name = new_name
            db.commit()
    finally:
        db.close()

    config.save()
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/site/add")
async def admin_site_add(
    request: Request,
    org_name: str = Form(...),
    site_name: str = Form(...),
    url: str = Form(...),
):
    if not _check_admin(request):
        raise HTTPException(status_code=401)

    site_name = site_name.strip()
    url = url.strip()
    if not site_name or not url:
        raise HTTPException(status_code=400, detail="Site name and URL are required")

    org_name = org_name.strip()
    if org_name not in config.orgs:
        raise HTTPException(status_code=400, detail="Org not found")

    config.orgs[org_name][site_name] = url
    config.sites[site_name] = url
    config.save()
    config._sync_db()
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/site/delete")
async def admin_site_delete(request: Request, site_name: str = Form(...)):
    if not _check_admin(request):
        raise HTTPException(status_code=401)

    site_name = site_name.strip()
    if site_name not in config.sites:
        raise HTTPException(status_code=400, detail="Site not found")

    for org_sites in config.orgs.values():
        org_sites.pop(site_name, None)
    empty_orgs = [k for k, v in config.orgs.items() if not v]
    for k in empty_orgs:
        del config.orgs[k]

    config.sites.pop(site_name, None)
    config.save()
    config._sync_db()
    SiteMonitor.prune_old_data()
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/site/rename")
async def admin_site_rename(
    request: Request,
    site_name: str = Form(...),
    new_name: str = Form(...),
):
    if not _check_admin(request):
        raise HTTPException(status_code=401)

    site_name = site_name.strip()
    new_name = new_name.strip()
    if not site_name or not new_name:
        raise HTTPException(status_code=400, detail="Both names are required")
    if site_name not in config.sites:
        raise HTTPException(status_code=400, detail="Site not found")
    if new_name == site_name:
        return RedirectResponse("/admin", status_code=303)

    url = config.sites.pop(site_name)
    config.sites[new_name] = url

    for org_sites in config.orgs.values():
        if site_name in org_sites:
            org_sites[new_name] = org_sites.pop(site_name)

    db = SessionLocal()
    try:
        site = db.query(Site).filter(Site.name == site_name).first()
        if site:
            site.name = new_name
            db.commit()
    finally:
        db.close()

    config.save()
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/status/set")
async def admin_status_set(
    request: Request,
    scope: str = Form(...),
    scope_name: str = Form(...),
    status_type: str = Form(...),
    message: str = Form(...),
):
    if not _check_admin(request):
        raise HTTPException(status_code=401)

    scope = scope.strip()
    scope_name = scope_name.strip()
    status_type = status_type.strip()
    message = message.strip()

    if scope not in ("org", "site"):
        raise HTTPException(status_code=400, detail="Scope must be org or site")
    if status_type not in ("degraded", "maintenance"):
        raise HTTPException(status_code=400, detail="Type must be degraded or maintenance")
    if not scope_name or not message:
        raise HTTPException(status_code=400, detail="Name and message are required")

    db = SessionLocal()
    try:
        if scope == "org":
            scope_id = _lookup_org_id(db, scope_name)
        else:
            scope_id = _lookup_site_id(db, scope_name)
        if scope_id is None:
            raise HTTPException(status_code=400, detail=f"{scope} '{scope_name}' not found in database")

        existing = (
            db.query(SiteStatus)
            .filter(
                SiteStatus.scope == scope,
                SiteStatus.scope_id == scope_id,
                SiteStatus.active == True,
            )
            .all()
        )
        now = datetime.now(timezone.utc)
        for s in existing:
            s.active = False
            s.ended_at = now

        db.add(SiteStatus(
            scope=scope,
            scope_id=scope_id,
            status_type=status_type,
            message=message,
            active=True,
        ))
        db.commit()
    finally:
        db.close()

    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/status/update")
async def admin_status_update(
    request: Request,
    status_id: int = Form(...),
    message: str = Form(...),
):
    if not _check_admin(request):
        raise HTTPException(status_code=401)

    message = message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    db = SessionLocal()
    try:
        s = db.query(SiteStatus).filter(SiteStatus.id == status_id).first()
        if not s or not s.active:
            raise HTTPException(status_code=400, detail="Status not found or not active")

        now = datetime.now(timezone.utc)
        updates = json.loads(s.updates) if s.updates else []
        updates.append({"message": s.message, "timestamp": now.isoformat()})
        s.message = message
        s.updates = json.dumps(updates)
        db.commit()
    finally:
        db.close()

    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/status/clear")
async def admin_status_clear(
    request: Request,
    status_id: int = Form(...),
):
    if not _check_admin(request):
        raise HTTPException(status_code=401)

    db = SessionLocal()
    try:
        s = db.query(SiteStatus).filter(SiteStatus.id == status_id).first()
        if s:
            s.active = False
            s.ended_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()

    return RedirectResponse("/admin", status_code=303)
