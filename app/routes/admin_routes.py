from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app
from datetime import date, datetime

from app.database import get_supabase
from app.utils import iso

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

ROLE_RANK = {"staff": 0, "branch_admin": 1, "org_admin": 2, "super_admin": 3}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("staff_id"):
            return redirect(url_for("admin.admin_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def role_required(min_role):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("staff_id"):
                return redirect(url_for("admin.admin_login", next=request.path))
            if ROLE_RANK.get(session.get("staff_role"), 0) < ROLE_RANK[min_role]:
                flash("คุณไม่มีสิทธิ์เข้าถึงหน้านี้")
                return redirect(url_for("admin.admin"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


def log_action(action, entity=None, details=None):
    supabase = get_supabase()
    log_data = {
        "staff_id": session.get("staff_id"),
        "branch_id": session.get("staff_branch_id"),
        "action": action,
        "entity": entity,
        "details": details
    }
    supabase.table("audit_log").insert(log_data).execute()


def scoped_branch_filter():
    if session.get("staff_role") in ("super_admin", "org_admin"):
        return None
    return session.get("staff_branch_id")


@admin_bp.route("/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        supabase = get_supabase()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        
        try:
            # 1. Login with Supabase Auth using a fresh anon client (so we don't pollute the global service role client!)
            import os
            from supabase import create_client
            url = current_app.config.get("SUPABASE_URL") or os.getenv("SUPABASE_URL")
            anon_key = current_app.config.get("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_ANON_KEY")
            auth_client = create_client(url, anon_key)
            
            auth_res = auth_client.auth.sign_in_with_password({"email": email, "password": password})
            user_id = auth_res.user.id
            
            # 2. Get Staff Profile using the global SERVICE ROLE client (which bypasses RLS)
            staff_res = supabase.table("staff").select("*").eq("auth_user_id", user_id).eq("is_active", True).execute()
            if not staff_res.data:
                flash("บัญชีไม่มีสิทธิ์เข้าใช้งานระบบ")
                return render_template("login.html")
                
            staff = staff_res.data[0]
            
            session.clear()
            session["staff_id"] = staff["id"]
            session["staff_username"] = staff["username"]
            session["staff_role"] = staff["role"]
            session["staff_branch_id"] = staff["branch_id"]
            session.permanent = True
            
            log_action("login")
            next_url = request.args.get("next") or url_for("admin.admin")
            return redirect(next_url)
            
        except Exception as e:
            flash("อีเมลหรือรหัสผ่านไม่ถูกต้อง")
            
    return render_template("login.html")


@admin_bp.route("/logout", methods=["POST"])
@login_required
def admin_logout():
    log_action("logout")
    session.clear()
    return redirect(url_for("admin.admin_login"))


def _default_branch_id():
    branch_id = scoped_branch_filter()
    if branch_id:
        return branch_id
    supabase = get_supabase()
    res = supabase.table("branches").select("id").eq("is_active", True).order("created_at").limit(1).execute()
    return res.data[0]["id"] if res.data else None


@admin_bp.route("/")
@login_required
def admin():
    branch_id = _default_branch_id()
    if not branch_id:
        flash("ยังไม่มีร้านที่ตั้งค่าไว้ในระบบ")
        return redirect(url_for("admin.admin_login"))
    return redirect(url_for("admin.kitchen", branch_id=branch_id))


def _assert_branch_access(branch_id):
    scoped = scoped_branch_filter()
    if scoped is None:
        return True
    return str(scoped) == str(branch_id)


@admin_bp.route("/kitchen/<branch_id>")
@login_required
def kitchen(branch_id):
    if not _assert_branch_access(branch_id):
        flash("ไม่มีสิทธิ์เข้าถึงร้านนี้")
        return redirect(url_for("admin.admin"))

    supabase = get_supabase()
    res = supabase.table("branches").select("*").eq("id", branch_id).execute()
    if not res.data:
        return redirect(url_for("admin.admin"))
    branch = res.data[0]

    # ดึงข้อมูล orders และ order_items ใน Request เดียว
    res = supabase.table("orders").select("*, order_items(*)").eq("branch_id", branch_id).in_("status", ["waiting", "preparing", "ready"]).order("created_at").execute()
    
    all_orders = res.data
    for o in all_orders:
        o["items"] = o.get("order_items", [])

    waiting = [o for o in all_orders if o["status"] == "waiting"]
    preparing = [o for o in all_orders if o["status"] == "preparing"]
    ready = [o for o in all_orders if o["status"] == "ready"]

    return render_template(
        "admin_room.html", branch=branch, waiting=waiting, preparing=preparing, ready=ready, iso=iso
    )


def _transition(order_id, from_statuses, to_status, timestamp_col, action):
    supabase = get_supabase()
    res = supabase.table("orders").select("*").eq("id", order_id).execute()
    if not res.data:
        return redirect(url_for("admin.admin"))
        
    order = res.data[0]
    if not _assert_branch_access(order["branch_id"]):
        return redirect(url_for("admin.admin"))
        
    if order["status"] not in from_statuses:
        return redirect(url_for("admin.kitchen", branch_id=order["branch_id"]))

    update_data = {
        "status": to_status,
        timestamp_col: datetime.utcnow().isoformat() + "Z",
        "called_by": session.get("staff_id")
    }
    supabase.table("orders").update(update_data).eq("id", order_id).execute()
    
    log_action(action, entity=f"order:{order_id}")
    return redirect(url_for("admin.kitchen", branch_id=order["branch_id"]))


@admin_bp.route("/order/<int:order_id>/start", methods=["POST"])
@login_required
def start_order(order_id):
    return _transition(order_id, ("waiting",), "preparing", "started_at", "start")


@admin_bp.route("/order/<int:order_id>/ready", methods=["POST"])
@login_required
def ready_order(order_id):
    return _transition(order_id, ("preparing",), "ready", "ready_at", "ready")


@admin_bp.route("/order/<int:order_id>/complete", methods=["POST"])
@login_required
def complete_order(order_id):
    return _transition(order_id, ("ready",), "completed", "completed_at", "complete")


@admin_bp.route("/order/<int:order_id>/cancel", methods=["POST"])
@login_required
def cancel_order(order_id):
    return _transition(order_id, ("waiting", "preparing"), "cancelled", "completed_at", "cancel")


@admin_bp.route("/menu")
@login_required
def menu_manage():
    branch_id = _default_branch_id()
    supabase = get_supabase()
    res = supabase.table("menu_items").select("*").eq("branch_id", branch_id).order("category").order("name").execute()
    return render_template("menu_manage.html", items=res.data, branch_id=branch_id)


@admin_bp.route("/menu/add", methods=["POST"])
@login_required
def menu_add():
    branch_id = request.form.get("branch_id")
    if not _assert_branch_access(branch_id):
        return redirect(url_for("admin.admin"))
        
    name = request.form.get("name", "").strip()
    price = request.form.get("price", "0").strip()
    category = request.form.get("category", "อาหาร").strip() or "อาหาร"
    
    if name and price:
        supabase = get_supabase()
        supabase.table("menu_items").insert({
            "branch_id": branch_id,
            "name": name,
            "price": float(price),
            "category": category
        }).execute()
        log_action("menu_add", entity=name)
        
    return redirect(url_for("admin.menu_manage"))


@admin_bp.route("/menu/<item_id>/toggle", methods=["POST"])
@login_required
def menu_toggle(item_id):
    supabase = get_supabase()
    res = supabase.table("menu_items").select("*").eq("id", item_id).execute()
    if res.data:
        item = res.data[0]
        if _assert_branch_access(item["branch_id"]):
            supabase.table("menu_items").update({
                "is_available": not item["is_available"]
            }).eq("id", item_id).execute()
            log_action("menu_toggle", entity=item["name"])
            
    return redirect(url_for("admin.menu_manage"))


@admin_bp.route("/dashboard")
@login_required
@role_required("branch_admin")
def dashboard():
    supabase = get_supabase()
    branch_id = scoped_branch_filter()
    today_iso = date.today().isoformat()
    
    query = supabase.table("orders").select("id, status, created_at, ready_at, total_price") \
        .gte("created_at", today_iso)
    if branch_id:
        query = query.eq("branch_id", branch_id)
    res_orders = query.execute()
    orders_today = res_orders.data
    
    total_today = len(orders_today)
    completed_today = sum(1 for o in orders_today if o["status"] == "completed")
    cancelled_today = sum(1 for o in orders_today if o["status"] == "cancelled")
    
    query_active = supabase.table("orders").select("id", count="exact").in_("status", ["waiting", "preparing"])
    if branch_id:
        query_active = query_active.eq("branch_id", branch_id)
    active_now = query_active.execute().count or 0
    
    prep_times = []
    for o in orders_today:
        if o["ready_at"]:
            try:
                c = datetime.fromisoformat(o["created_at"].replace("Z", "+00:00"))
                r = datetime.fromisoformat(o["ready_at"].replace("Z", "+00:00"))
                prep_times.append((r - c).total_seconds())
            except Exception:
                pass
                
    avg_prep_minutes = round(sum(prep_times) / len(prep_times) / 60, 1) if prep_times else 0
    revenue_today = sum(o["total_price"] for o in orders_today if o["status"] != "cancelled")
    
    top_items = []
    order_ids = [o["id"] for o in orders_today if o["status"] != "cancelled"]
    if order_ids:
        # Since 'in_' has a URL length limit, chunking might be needed for huge arrays, 
        # but for a daily branch dashboard it should be fine.
        res_items = supabase.table("order_items").select("item_name, quantity").in_("order_id", order_ids).execute()
        item_counts = {}
        for i in res_items.data:
            item_counts[i["item_name"]] = item_counts.get(i["item_name"], 0) + i["quantity"]
        
        top_items = [{"name": k, "qty": v} for k, v in sorted(item_counts.items(), key=lambda x: x[1], reverse=True)[:10]]

    return render_template(
        "dashboard.html",
        total_today=total_today,
        completed_today=completed_today,
        cancelled_today=cancelled_today,
        active_now=active_now,
        avg_prep_minutes=avg_prep_minutes,
        revenue_today=revenue_today,
        top_items=top_items,
    )
