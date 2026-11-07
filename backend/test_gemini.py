"""One-off check that the Gemini extraction model is reachable.

Run from backend/:  ../.venv/Scripts/python.exe test_gemini.py
(Not a pytest test — pytest only collects tests/.)
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import errors

load_dotenv(Path(__file__).parent / ".env")
api_key = os.getenv("GEMINI_API_KEY", "").strip()
model = os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip()

if not api_key:
    sys.exit("GEMINI_API_KEY is empty — paste your key into backend/.env")

client = genai.Client(api_key=api_key)
try:
    resp = client.models.generate_content(model=model, contents="Reply with exactly: OK")
except errors.APIError as e:
    sys.exit(f"FAILED  model={model}  {e.code} {e.status}: {e.message}")

print(f"OK  model={model}  reply={resp.text.strip()!r}")
