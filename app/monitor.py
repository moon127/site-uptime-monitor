import asyncio
import time
from datetime import datetime, timezone, timedelta

import httpx

from app.database import SessionLocal
from app.models import CheckResult, Site
from app.config import config


class SiteMonitor:
    _instance = None
    _task: asyncio.Task | None = None

    def __init__(self):
        SiteMonitor._instance = self
        self._task = None

    async def check_site(self, name: str, url: str):
        start = time.perf_counter()
        db = SessionLocal()
        try:
            site = db.query(Site).filter(Site.name == name).first()
            if not site:
                return
            site_id = site.id

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, follow_redirects=True)
                elapsed = (time.perf_counter() - start) * 1000
                result = CheckResult(
                    site_id=site_id,
                    url=url,
                    timestamp=datetime.now(timezone.utc),
                    status_code=resp.status_code,
                    response_time_ms=round(elapsed, 2),
                    is_up=resp.status_code < 400,
                )
                db.add(result)
                db.commit()
        except Exception:
            elapsed = (time.perf_counter() - start) * 1000
            site = db.query(Site).filter(Site.name == name).first()
            if not site:
                return
            result = CheckResult(
                site_id=site.id,
                url=url,
                timestamp=datetime.now(timezone.utc),
                status_code=0,
                response_time_ms=round(elapsed, 2),
                is_up=False,
            )
            db.add(result)
            db.commit()
        finally:
            db.close()

    async def run(self):
        while True:
            if config.check_and_reload():
                self.prune_old_data()

            if not config.sites:
                await asyncio.sleep(config.poll_interval)
                continue

            tasks = [self.check_site(name, url) for name, url in config.sites.items()]
            await asyncio.gather(*tasks)
            await asyncio.sleep(config.poll_interval)

    def start(self):
        self._task = asyncio.create_task(self.run())

    @staticmethod
    def prune_old_data():
        cutoff = datetime.now(timezone.utc) - timedelta(days=config.retention_days)
        db = SessionLocal()
        try:
            db.query(CheckResult).filter(CheckResult.timestamp < cutoff).delete()

            active_site_names = list(config.sites.keys())
            active_site_ids = [
                r[0] for r in db.query(Site.id).filter(Site.name.in_(active_site_names)).all()
            ] if active_site_names else []
            if active_site_ids:
                db.query(CheckResult).filter(
                    ~CheckResult.site_id.in_(active_site_ids)
                ).delete()
            else:
                db.query(CheckResult).delete()
            db.commit()
        finally:
            db.close()
