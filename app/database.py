import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DB_DIR = Path(os.environ.get("DATA_DIR", str(Path(__file__).resolve().parent.parent)))
DB_PATH = DB_DIR / "sitechecker.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
