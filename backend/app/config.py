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
    RK_STOREFRONT_URL = os.getenv("RK_STOREFRONT_URL", "")
    RK_STOREFRONT_BOOTSTRAP_SECRET = os.getenv("RK_STOREFRONT_BOOTSTRAP_SECRET", "")
    RK_STOREFRONT_CLIENT_ID = os.getenv("RK_STOREFRONT_CLIENT_ID", "rk-stock-linesheets")
    FX_API_URL = os.getenv("FX_API_URL", "")
    FX_API_KEY = os.getenv("FX_API_KEY", "")
    FX_API_TIMEOUT_SECONDS = float(os.getenv("FX_API_TIMEOUT_SECONDS", "5"))
    CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "")
    CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY", "")
    CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "")
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024
