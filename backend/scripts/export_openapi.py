"""Run from backend; no running API or database required."""

import json
from pathlib import Path

from app.main import app

path = Path(__file__).resolve().parents[2] / "frontend" / "openapi.json"
path.write_text(json.dumps(app.openapi(), indent=2) + "\n")
print(f"Exported {path.name}")
