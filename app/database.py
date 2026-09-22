from flask import current_app
from supabase import create_client


def get_supabase():
    """A service client per Flask application, never reused for user sign-in."""
    injected = current_app.config.get("SUPABASE_CLIENT")
    if injected is not None:
        return injected
    client = current_app.extensions.get("supabase")
    if client is None:
        client = create_client(current_app.config["SUPABASE_URL"], current_app.config["SUPABASE_SERVICE_ROLE_KEY"])
        current_app.extensions["supabase"] = client
    return client


def init_app(app):
    app.extensions.pop("supabase", None)
