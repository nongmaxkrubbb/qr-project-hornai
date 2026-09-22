import os


class Config:
    @staticmethod
    def values():
        production = os.getenv("APP_ENV", os.getenv("FLASK_ENV", "development")) == "production"
        return {
            "SECRET_KEY": os.getenv("SECRET_KEY", ""),
            "SUPABASE_URL": os.getenv("SUPABASE_URL", ""),
            "SUPABASE_ANON_KEY": os.getenv("SUPABASE_ANON_KEY", ""),
            "SUPABASE_SERVICE_ROLE_KEY": os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""),
            "APP_ENV": "production" if production else "development",
            "PUBLIC_BASE_URL": os.getenv("PUBLIC_BASE_URL", ""),
            "SESSION_COOKIE_HTTPONLY": True,
            "SESSION_COOKIE_SECURE": production,
            "SESSION_COOKIE_SAMESITE": "Lax",
            "PERMANENT_SESSION_LIFETIME": int(os.getenv("CUSTOMER_SESSION_LIFETIME_SECONDS", "3024000")),
            "STAFF_SESSION_LIFETIME_SECONDS": int(os.getenv("SESSION_LIFETIME_SECONDS", "28800")),
            "SESSION_REDIS_URL": os.getenv("SESSION_REDIS_URL", ""),
            "SESSION_COOKIE_NAME": "__Host-queue_session" if production else "queue_session",
            "SESSION_COOKIE_PATH": "/",
            "SESSION_PERMANENT": True,
            "SESSION_REFRESH_EACH_REQUEST": False,
            "SESSION_KEY_PREFIX": "queue:session:v1:",
            "SESSION_SERIALIZATION_FORMAT": "msgpack",
            "MAX_CONTENT_LENGTH": 6 * 1024 * 1024,
            "MAX_SLIP_BYTES": 5 * 1024 * 1024,
            "RATELIMIT_STORAGE_URI": os.getenv("RATELIMIT_STORAGE_URI", "memory://"),
            "RATELIMIT_HEADERS_ENABLED": True,
            "TRUSTED_PROXY_COUNT": int(os.getenv("TRUSTED_PROXY_COUNT", "0")),
            "VAPID_PUBLIC_KEY": os.getenv("VAPID_PUBLIC_KEY", ""),
            "VAPID_PRIVATE_KEY": os.getenv("VAPID_PRIVATE_KEY", ""),
            "VAPID_SUBJECT": os.getenv("VAPID_SUBJECT", ""),
            "PUSH_ALLOWED_HOSTS": os.getenv("PUSH_ALLOWED_HOSTS", "fcm.googleapis.com,updates.push.services.mozilla.com,web.push.apple.com").split(","),
        }
