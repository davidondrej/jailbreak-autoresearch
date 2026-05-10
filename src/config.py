from __future__ import annotations

import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_dotenv(path: Path | None = None) -> None:
    env_path = path or ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def load_models(path: Path | None = None) -> list[str]:
    model_path = path or ROOT / "models.json"
    data = json.loads(model_path.read_text(encoding="utf-8"))
    if data.get("provider") != "openrouter":
        raise ValueError("models.json must use provider=openrouter")
    models = data.get("models", [])
    if not isinstance(models, list) or not all(isinstance(m, str) for m in models):
        raise ValueError("models.json must contain a string list at models")
    return models


def require_api_key() -> str:
    load_dotenv()
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is missing; create .env first")
    return key
