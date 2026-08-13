import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


API_ID = int(required("API_ID"))
API_HASH = required("API_HASH")
BOT_TOKEN = required("BOT_TOKEN")
SESSION_ENCRYPTION_KEY = required("SESSION_ENCRYPTION_KEY")
TARGET_CHAT = "@tbilisi_arendaa"
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "velven.db"
UPLOADS_DIR = BASE_DIR / "uploads"
