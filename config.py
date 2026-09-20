import os


def _require(name):
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Copy .env.example to .env and fill it in before running the app."
        )
    return val


class Config:
    # ----- Secrets: ต้องมาจาก ENV เท่านั้น ห้าม hardcode ในโค้ดเด็ดขาด -----
    SECRET_KEY = _require("SECRET_KEY")

    # Supabase project
    SUPABASE_URL = _require("SUPABASE_URL")
    SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
    SUPABASE_SERVICE_ROLE_KEY = _require("SUPABASE_SERVICE_ROLE_KEY")

    # ----- Session / cookie hardening -----
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = os.environ.get("FLASK_ENV") == "production"
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = int(os.environ.get("SESSION_LIFETIME_SECONDS", 8 * 3600))

    # ----- Rate limiting (ดู app/__init__.py) -----
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
