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
CONFIG_PATH = DATA_DIR / "config.json"  # runtime config written by the Settings page (gitignored)

load_dotenv(BACKEND_DIR / ".env")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip()
PIPELINE_VERSION = "0.3.0"  # stamped on every Processed Invoice Record
# Demo safety: narratives come from the cache or the template, never a live Gemini call.
NARRATIVE_CACHE_ONLY = os.getenv("NARRATIVE_CACHE_ONLY", "0").strip() == "1"


def load_config():
    """The Settings page's saved config if there is one, else the shipped default."""
    path = CONFIG_PATH if CONFIG_PATH.exists() else DATA_DIR / "config_default.json"
    return json.loads(path.read_text(encoding="utf-8"))


def save_config(config: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
