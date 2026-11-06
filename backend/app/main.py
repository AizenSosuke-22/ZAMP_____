import json
from pathlib import Path

from fastapi import FastAPI

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

app = FastAPI(title="Zamp Invoice AP")


@app.get("/health")
def health():
    config = json.loads((DATA_DIR / "config_default.json").read_text(encoding="utf-8"))
    return {"status": "ok", "config_version": config["config_version"]}
