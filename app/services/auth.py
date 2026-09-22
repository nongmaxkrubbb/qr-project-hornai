"""Server-side staff identity and branch authorization.

Session values are display hints only. Every request reloads the active profile
before any service-role query can read or mutate a branch's data.
"""
from functools import wraps
from time import time
from urllib.parse import urlsplit
from uuid import UUID

from flask import abort, current_app, g, redirect, request, session, url_for

from app.database import get_supabase

ROLE_RANK = {"staff": 0, "branch_admin": 1, "org_admin": 2, "super_admin": 3}


def safe_next_url(value):
    """Only accept same-origin, absolute-path redirects (including backslashes)."""
    if not value or not value.startswith("/") or value.startswith("//"):
        return url_for("admin.admin")
    if "\\" in value or any(ord(char) < 32 for char in value):
        return url_for("admin.admin")
    parts = urlsplit(value)
    if parts.scheme or parts.netloc:
        return url_for("admin.admin")
    return value


def valid_uuid(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        abort(404)


def profile_is_valid(staff, db):
    if not staff or not staff.get("is_active") or not staff.get("auth_user_id") or staff.get("role") not in ROLE_RANK:
        return False
    role = staff["role"]
    if role == "super_admin":
        return True
    organization_id = staff.get("organization_id")
    if not organization_id:
        return False
    if role == "org_admin":
        return bool(db.table("organizations").select("id").eq("id", organization_id).limit(1).execute().data)
    if not staff.get("branch_id"):
        return False
    return bool(db.table("branches").select("id").eq("id", staff["branch_id"])
                .eq("organization_id", organization_id).limit(1).execute().data)


def current_staff():
    if hasattr(g, "staff"):
        return g.staff
    g.staff = None
    staff_id = session.get("staff_id")
    if not staff_id:
        return None
    try:
        expired = float(session.get("staff_auth_until", 0)) <= time()
    except (TypeError, ValueError):
        expired = True
    if expired:
        clear_staff_session()
        return None
    db = get_supabase()
    rows = db.table("staff").select("*").eq("id", valid_uuid(staff_id)).limit(1).execute().data
    staff = rows[0] if rows else None
    if not profile_is_valid(staff, db):
        clear_staff_session()
        return None
    g.staff = staff
    # Templates may continue using session fields, but only after this refresh.
    display_fields = {
        "staff_id": staff["id"], "staff_username": staff["username"],
        "staff_role": staff["role"], "staff_branch_id": staff.get("branch_id"),
        "staff_organization_id": staff.get("organization_id"),
    }
    if any(session.get(key) != value for key, value in display_fields.items()):
        session.update(display_fields)
    return staff


def clear_staff_session():
    """Expire staff access while preserving the device's customer orders/cart."""
    for key in list(session):
        if key.startswith("staff_") or key == "walk_in_attempts":
            session.pop(key, None)
    g.staff = None


def rotate_session():
    regenerate = getattr(current_app.session_interface, "regenerate", None)
    if regenerate:
        # Flask-Session regenerates only a nonempty session.
        session["_rotate"] = True
        regenerate(session)
        session.pop("_rotate", None)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_staff():
            return redirect(url_for("admin.admin_login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)
    return wrapped


def role_required(min_role):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if ROLE_RANK[current_staff()["role"]] < ROLE_RANK[min_role]:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def accessible_branches():
    staff = current_staff()
    if not staff:
        abort(403)
    query = get_supabase().table("branches").select("*")
    if staff["role"] == "org_admin":
        query = query.eq("organization_id", staff["organization_id"])
    elif staff["role"] != "super_admin":
        query = query.eq("id", staff["branch_id"]).eq("organization_id", staff["organization_id"])
    return query.order("name").execute().data or []


def require_branch(branch_id):
    branch_id = valid_uuid(branch_id)
    staff = current_staff()
    if not staff:
        abort(403)
    query = get_supabase().table("branches").select("*").eq("id", branch_id)
    if staff["role"] == "org_admin":
        query = query.eq("organization_id", staff["organization_id"])
    elif staff["role"] != "super_admin":
        if str(staff["branch_id"]) != branch_id:
            abort(404)
        query = query.eq("organization_id", staff["organization_id"])
    rows = query.limit(1).execute().data
    if not rows:
        abort(404)
    return rows[0]
