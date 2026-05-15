from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.orm import declarative_base
from datetime import datetime, timezone

Base = declarative_base()


class Org(Base):
    __tablename__ = "orgs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)


class Site(Base):
    __tablename__ = "sites"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    url = Column(String, nullable=False)
    org_id = Column(Integer, ForeignKey("orgs.id"), nullable=True)


class CheckResult(Base):
    __tablename__ = "check_results"

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    url = Column(String, nullable=False)
    timestamp = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )
    status_code = Column(Integer, nullable=False)
    response_time_ms = Column(Float, nullable=False)
    is_up = Column(Boolean, nullable=False)


class AdminUser(Base):
    __tablename__ = "admin_user"

    id = Column(Integer, primary_key=True, index=True)
    password_hash = Column(String, nullable=False)
    salt = Column(String, nullable=False)
    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class SiteStatus(Base):
    __tablename__ = "site_status"

    id = Column(Integer, primary_key=True, index=True)
    scope = Column(String, nullable=False)
    scope_id = Column(Integer, nullable=False)
    status_type = Column(String, nullable=False)
    message = Column(String, nullable=False)
    updates = Column(Text, nullable=True)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    ended_at = Column(DateTime, nullable=True)
