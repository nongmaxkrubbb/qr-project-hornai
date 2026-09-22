"""Keep carts and order capabilities on the server, outside cookie size limits."""
from pathlib import Path
from urllib.parse import urlsplit

from flask_session import Session
from redis import Redis
from redis.exceptions import RedisError
from werkzeug.wrappers import Response


class StorageUnavailable:
    """Session loading/saving can fail outside Flask's request error handlers."""

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        try:
            return self.app(environ, start_response)
        except RedisError:
            # Never clear a valid browser session because Redis is unavailable.
            response = Response(
                "ระบบจัดเก็บข้อมูลชั่วคราวไม่พร้อม กรุณารอสักครู่แล้วเปิดหน้าเดิมอีกครั้ง",
                status=503, content_type="text/plain; charset=utf-8",
                headers={"Retry-After": "10", "Cache-Control": "no-store"},
            )
            return response(environ, start_response)


def init_sessions(app):
    redis_url = app.config.get("SESSION_REDIS_URL")
    if not redis_url and urlsplit(app.config["RATELIMIT_STORAGE_URI"]).scheme in ("redis", "rediss"):
        redis_url = app.config["RATELIMIT_STORAGE_URI"]
    if redis_url:
        if urlsplit(redis_url).scheme not in ("redis", "rediss"):
            raise RuntimeError("SESSION_REDIS_URL must use redis:// or rediss://.")
        client = Redis.from_url(redis_url, socket_connect_timeout=3, socket_timeout=3,
                                health_check_interval=30)
        app.config.update(SESSION_TYPE="redis", SESSION_REDIS=client)
        app.extensions["session_redis"] = client
    elif app.config["APP_ENV"] == "production":
        raise RuntimeError("Production requires Redis sessions. Set SESSION_REDIS_URL or a Redis RATELIMIT_STORAGE_URI.")
    else:
        from cachelib.file import FileSystemCache
        directory = Path(app.instance_path) / "sessions"
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        app.config.update(SESSION_TYPE="cachelib", SESSION_CACHELIB=FileSystemCache(
            cache_dir=str(directory), threshold=10000, mode=0o600,
        ))
    Session(app)
    app.wsgi_app = StorageUnavailable(app.wsgi_app)
