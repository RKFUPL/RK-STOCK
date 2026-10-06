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
    LOCAL_SESSION_COOKIE_NAME = os.getenv("LOCAL_SESSION_COOKIE_NAME", "rk_stock_session")
    LOCAL_SESSION_COOKIE_DOMAIN = os.getenv("LOCAL_SESSION_COOKIE_DOMAIN", "")
    LOCAL_SESSION_COOKIE_SECURE = os.getenv("FLASK_ENV", "development").lower() == "production"
    LOCAL_SESSION_DAYS = int(os.getenv("LOCAL_SESSION_DAYS", "30"))
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
    SHARED_AUTH_URL = os.getenv("SHARED_AUTH_URL", "")
    SHARED_SESSION_INTERNAL_SECRET = os.getenv("SHARED_SESSION_INTERNAL_SECRET", "")
    SHARED_SESSION_COOKIE_NAME = os.getenv("SHARED_SESSION_COOKIE_NAME", "rk_shared_session")
    SHARED_SESSION_COOKIE_DOMAIN = os.getenv("SHARED_SESSION_COOKIE_DOMAIN", ".rashikapoor.co.in")
    SHARED_SESSION_COOKIE_SECURE = os.getenv("FLASK_ENV", "development").lower() == "production"
    SHARED_SESSION_DAYS = int(os.getenv("SHARED_SESSION_DAYS", "30"))
    CREDENTIAL_SYNC_HANDOFF_SECRET = os.getenv("CREDENTIAL_SYNC_HANDOFF_SECRET", "")
    CREDENTIAL_SYNC_HANDOFF_TTL_SECONDS = int(os.getenv("CREDENTIAL_SYNC_HANDOFF_TTL_SECONDS", "60"))
    RK_WEB_CREDENTIAL_SYNC_SECRET = os.getenv("RK_WEB_CREDENTIAL_SYNC_SECRET", "")
    RK_WEB_CREDENTIAL_SYNC_SCOPES = {item.strip() for item in os.getenv("RK_WEB_CREDENTIAL_SYNC_SCOPES", "").split(",") if item.strip()}
