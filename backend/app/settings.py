"""Paths + env. Modules read these attributes at call time so tests can monkeypatch them."""
import json
import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"
DB_PATH = DATA_DIR / "ap.db"
UPLOAD_DIR = DATA_DIR / "uploads"
CACHE_DIR = DATA_DIR / "cache"

load_dotenv(BACKEND_DIR / ".env")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip()


def load_config():
    return json.loads((DATA_DIR / "config_default.json").read_text(encoding="utf-8"))
