import configparser
import os
from pathlib import Path

from app.database import SessionLocal
from app.models import Org, Site

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR", str(APP_DIR)))
CONFIG_PATH = DATA_DIR / "config.ini"


class Config:
    def __init__(self):
        self.sites: dict[str, str] = {}
        self.orgs: dict[str, dict[str, str]] = {}
        self.retention_days: int = 90
        self.poll_interval: int = 60
        self._last_mtime: float = 0
        self._load()

    def _load(self):
        self.sites.clear()
        self.orgs.clear()
        parser = configparser.ConfigParser()
        if CONFIG_PATH.exists():
            parser.read(CONFIG_PATH)
            self._last_mtime = CONFIG_PATH.stat().st_mtime

            for section in parser.sections():
                if section.startswith("org:"):
                    org_name = section[4:].strip()
                    if org_name:
                        org_sites = {}
                        for key, value in parser.items(section):
                            org_sites[key.strip()] = value.strip()
                        if org_sites:
                            self.orgs[org_name] = org_sites
                            self.sites.update(org_sites)

            if parser.has_section("sites"):
                ungrouped = {}
                for key, value in parser.items("sites"):
                    ungrouped[key.strip()] = value.strip()
                self.sites.update(ungrouped)
                if self.orgs and ungrouped:
                    existing = set()
                    for org_sites in self.orgs.values():
                        existing.update(org_sites.keys())
                    remaining = {k: v for k, v in ungrouped.items() if k not in existing}
                    if remaining:
                        self.orgs.setdefault("Ungrouped", {}).update(remaining)

            if parser.has_section("settings"):
                self.retention_days = parser.getint(
                    "settings", "retention_days", fallback=90
                )
                self.poll_interval = parser.getint(
                    "settings", "poll_interval", fallback=60
                )

    def _sync_db(self):
        db = SessionLocal()
        try:
            # Remove sites no longer in config (before orgs to respect FK)
            for site in db.query(Site).all():
                if site.name not in self.sites:
                    db.delete(site)

            # Remove orgs no longer in config
            for org in db.query(Org).all():
                if org.name not in self.orgs:
                    db.delete(org)

            for org_name in list(self.orgs.keys()):
                org = db.query(Org).filter(Org.name == org_name).first()
                if not org:
                    org = Org(name=org_name)
                    db.add(org)
                    db.flush()

            for site_name, url in self.sites.items():
                site = db.query(Site).filter(Site.name == site_name).first()
                if not site:
                    site = Site(name=site_name, url=url)
                    db.add(site)
                    db.flush()
                else:
                    site.url = url

            if self.orgs:
                for org_name, org_sites in self.orgs.items():
                    org = db.query(Org).filter(Org.name == org_name).first()
                    if not org:
                        continue
                    for site_name in org_sites:
                        site = db.query(Site).filter(Site.name == site_name).first()
                        if site:
                            site.org_id = org.id

            db.commit()
        finally:
            db.close()

    def save(self):
        parser = configparser.ConfigParser()

        if self.orgs:
            for org_name, org_sites in self.orgs.items():
                section = f"org:{org_name}"
                parser[section] = {}
                for key, value in org_sites.items():
                    parser[section][key] = value
            all_org_sites = set()
            for org_sites in self.orgs.values():
                all_org_sites.update(org_sites.keys())
            leftover = {k: v for k, v in self.sites.items() if k not in all_org_sites}
            if leftover:
                parser["sites"] = leftover
        else:
            parser["sites"] = dict(self.sites)

        parser["settings"] = {
            "retention_days": str(self.retention_days),
            "poll_interval": str(self.poll_interval),
        }

        with open(CONFIG_PATH, "w") as f:
            parser.write(f)

    def check_and_reload(self) -> bool:
        if not CONFIG_PATH.exists():
            return False
        try:
            mtime = CONFIG_PATH.stat().st_mtime
        except OSError:
            return False
        if mtime <= self._last_mtime:
            return False

        old_sites = set(self.sites.keys())
        old_orgs = {k: dict(v) for k, v in self.orgs.items()}
        old_retention = self.retention_days
        old_interval = self.poll_interval

        self._load()
        self._sync_db()

        changed = (
            old_sites != set(self.sites.keys())
            or old_orgs != self.orgs
            or old_retention != self.retention_days
            or old_interval != self.poll_interval
        )
        return changed


config = Config()
