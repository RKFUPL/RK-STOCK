import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


class Config:
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    MONGO_DB = os.getenv("MONGO_DB", "rk_operations")
    MONGO_SERVER_SELECTION_TIMEOUT_MS = int(os.getenv("MONGO_SERVER_SELECTION_TIMEOUT_MS", "30000"))
    MONGO_CONNECT_ATTEMPTS = int(os.getenv("MONGO_CONNECT_ATTEMPTS", "3"))
    MONGO_CONNECT_BACKOFF_SECONDS = float(os.getenv("MONGO_CONNECT_BACKOFF_SECONDS", "1"))
    JWT_SECRET = os.getenv("JWT_SECRET", "development-only-change-this-secret")
    JWT_TTL_SECONDS = int(os.getenv("JWT_TTL_SECONDS", "28800"))
    UPLOAD_DIR = os.getenv("UPLOAD_DIR", str(Path(__file__).resolve().parents[1] / "uploads"))
    FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024
