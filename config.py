import os
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "finance-assistant-dev-key")
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    TRUST_PROXY_HEADERS = os.getenv("TRUST_PROXY_HEADERS", "false").lower() == "true"
    VERCEL = os.getenv("VERCEL", "").lower() == "1"
    DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    JSON_SORT_KEYS = False
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
    STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    STRIPE_PREMIUM_PRICE_ID = os.getenv("STRIPE_PREMIUM_PRICE_ID", "")
    ALLOW_STRIPE_LIVE = os.getenv("ALLOW_STRIPE_LIVE", "false").lower() == "true"
    APP_BASE_URL = os.getenv("APP_BASE_URL", "http://127.0.0.1:5000")
    RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://")
    API_INSIGHT_RATE_LIMIT = os.getenv("API_INSIGHT_RATE_LIMIT", "10 per minute")
    API_PREMIUM_INSIGHT_RATE_LIMIT = os.getenv("API_PREMIUM_INSIGHT_RATE_LIMIT", "20 per minute")
    INSIGHT_API_KEY = os.getenv("INSIGHT_API_KEY", "")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    DATABASE_URL = os.getenv("DATABASE_URL", "")
    REQUIRE_POSTGRES = os.getenv("REQUIRE_POSTGRES", "false").lower() == "true"
    SENTRY_DSN = os.getenv("SENTRY_DSN", "")
    REQUIRE_EMAIL_VERIFICATION = os.getenv("REQUIRE_EMAIL_VERIFICATION", "false").lower() == "true"
    MAIL_SUPPRESS_SEND = os.getenv("MAIL_SUPPRESS_SEND", "true").lower() == "true"
    MAIL_SERVER = os.getenv("MAIL_SERVER", "")
    MAIL_PORT = int(os.getenv("MAIL_PORT") or "587")
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", "")
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "").strip().lower()


config = Config()
