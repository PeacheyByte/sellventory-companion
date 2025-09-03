# settings.py
import json, os
from dataclasses import dataclass, asdict

APP_DIR = os.path.join(os.path.expanduser("~"), ".sellventory_companion")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")

@dataclass
class AppConfig:
    library_dir: str | None = None  # path that contains sellventory.db and images/

def ensure_app_dir() -> None:
    os.makedirs(APP_DIR, exist_ok=True)

def load_config() -> AppConfig:
    ensure_app_dir()
    if not os.path.exists(CONFIG_PATH):
        return AppConfig()
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return AppConfig(**data)
    except Exception:
        return AppConfig()

def save_config(cfg: AppConfig) -> None:
    ensure_app_dir()
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(asdict(cfg), f, indent=2)
