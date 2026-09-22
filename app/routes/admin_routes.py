"""Staff workflows. All service-role operations require a fresh scoped profile."""
import json
import re
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from time import time as timestamp
from urllib.parse import urlsplit
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, session, url_for

from app.database import get_supabase
from app.services.auth import (ROLE_RANK, accessible_branches, current_staff,
                               clear_staff_session, login_required, profile_is_valid, require_branch,
                               role_required, rotate_session, safe_next_url, valid_uuid)
from app.services.errors import UserError, database_error
from app.utils import iso

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def log_action(action, entity=None, details=None, branch_id=None):
    staff = current_staff()
    get_supabase().table("audit_log").insert({
        "staff_id": staff["id"] if staff else None,
        "branch_id": branch_id if branch_id is not None else (staff or {}).get("branch_id"),
        "action": action, "entity": entity, "details": details or {},
    }).execute()


@admin_bp.route("/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        from supabase import create_client
        email = request.form.get("email", "").strip()[:254]
        password = request.form.get("password", "")
        try:
            auth_client = create_client(current_app.config["SUPABASE_URL"], current_app.config["SUPABASE_ANON_KEY"])
            result = auth_client.auth.sign_in_with_password({"email": email, "password": password})
            if not result.user:
                raise ValueError("Missing authenticated user")
            db = get_supabase()
            rows = db.table("staff").select("*").eq("auth_user_id", str(result.user.id)).limit(1).execute().data
            staff = rows[0] if rows else None
            if not profile_is_valid(staff, db):
                raise ValueError("Inactive or unscoped profile")
        except Exception:
            # Never include auth credentials, provider errors, or whether an email exists.
            flash("เข้าสู่ระบบไม่ได้ โปรดตรวจสอบบัญชีและสิทธิ์กับผู้ดูแล")
            return render_template("login.html"), 401
        clear_staff_session()
        rotate_session()
        session["staff_id"] = staff["id"]
        session["staff_auth_until"] = timestamp() + current_app.config.get("STAFF_SESSION_LIFETIME_SECONDS", 28800)
        session.permanent = True
        g.staff = staff
        session.update(staff_username=staff["username"], staff_role=staff["role"],
                       staff_branch_id=staff.get("branch_id"), staff_organization_id=staff.get("organization_id"))
        log_action("login")
        return redirect(safe_next_url(request.args.get("next")))
    return render_template("login.html")


@admin_bp.route("/logout", methods=["POST"])
@login_required
def admin_logout():
    try:
        log_action("logout")
    finally:
        rotate_session()
        clear_staff_session()
    return redirect(url_for("admin.admin_login"))


def _selected_branch():
    branch_id = request.args.get("branch_id") or request.form.get("branch_id")
    if branch_id:
        return require_branch(branch_id)
    branches = accessible_branches()
    if not branches:
        abort(404)
    return branches[0]


@admin_bp.route("/")
@login_required
def admin():
    return render_template("admin_branches.html", branches=accessible_branches(), staff=current_staff())


def _kitchen_context(branch_id):
    branch = require_branch(branch_id)
    db = get_supabase()
    db.rpc("expire_unpaid_orders", {"p_branch_id": branch["id"]}).execute()
    rows = db.table("orders").select("*,order_items(*)").eq("branch_id", branch["id"]) \
        .in_("status", ["pending_payment", "waiting", "preparing", "ready"]).order("created_at").limit(1000).execute().data or []
    recent = db.table("orders").select("*,order_items(*)").eq("branch_id", branch["id"]) \
        .in_("status", ["completed", "cancelled"]).order("created_at", desc=True).limit(30).execute().data or []
    refunds = db.table("orders").select("*,order_items(*)").eq("branch_id", branch["id"]) \
        .eq("payment_status", "refund_due").order("created_at").limit(100).execute().data or []
    seen = {row["id"] for row in recent}
    recent = [row for row in refunds if row["id"] not in seen] + recent
    for row in rows + recent:
        row["items"] = row.get("order_items", [])
    context = {status: [row for row in rows if row["status"] == status]
               for status in ("pending_payment", "waiting", "preparing", "ready")}
    context.update(branch=branch, branches=accessible_branches(), recent=recent,
                   iso=iso, staff=current_staff(), updated_at=datetime.now(ZoneInfo("UTC")).isoformat())
    return context


@admin_bp.route("/kitchen/<branch_id>")
@login_required
def kitchen(branch_id):
    return render_template("admin_room.html", **_kitchen_context(branch_id))


@admin_bp.route("/kitchen/<branch_id>/board")
@login_required
def kitchen_board(branch_id):
    response = current_app.make_response(render_template("_kitchen_board.html", **_kitchen_context(branch_id)))
    response.headers["Cache-Control"] = "no-store"
    return response


def _scoped_order(order_id):
    rows = get_supabase().table("orders").select("*").eq("id", order_id).limit(1).execute().data
    if not rows:
        abort(404)
    require_branch(rows[0]["branch_id"])
    return rows[0]


def _order_action(order_id, action):
    order = _scoped_order(order_id)
    reason = request.form.get("reason", "").strip()
    reference = request.form.get("reference", "").strip()
    expected_slip_path = request.form.get("expected_slip_path", "").strip()
    if len(reason) > 500 or len(reference) > 120 or len(expected_slip_path) > 512:
        abort(400)
    if action in ("cancel", "reject", "refund", "incident") and not reason:
        flash("กรุณาระบุเหตุผลเพื่อให้ตรวจสอบย้อนหลังได้")
        return redirect(url_for("admin.kitchen", branch_id=order["branch_id"]))
    # The RPC locks the row, verifies the current staff scope and writes the audit
    # event in the same transaction as the transition.
    get_supabase().rpc("order_action", {"p_order_id": order_id, "p_staff_id": current_staff()["id"],
                                       "p_action": action, "p_reason": reason, "p_reference": reference,
                                       "p_expected_slip_path": expected_slip_path or None}).execute()
    flash("บันทึกออเดอร์แล้ว")
    return redirect(url_for("admin.kitchen", branch_id=order["branch_id"]))


@admin_bp.route("/order/<int:order_id>/start", methods=["POST"])
@login_required
def start_order(order_id):
    return _order_action(order_id, "start")


@admin_bp.route("/order/<int:order_id>/ready", methods=["POST"])
@login_required
def ready_order(order_id):
    return _order_action(order_id, "ready")


@admin_bp.route("/order/<int:order_id>/complete", methods=["POST"])
@login_required
def complete_order(order_id):
    return _order_action(order_id, "complete")


@admin_bp.route("/order/<int:order_id>/cancel", methods=["POST"])
@login_required
def cancel_order(order_id):
    return _order_action(order_id, "cancel")


@admin_bp.route("/order/<int:order_id>/payment/<action>", methods=["POST"])
@login_required
def payment_action(order_id, action):
    if action not in ("verify", "reject", "cash", "refund"):
        abort(404)
    return _order_action(order_id, action)


@admin_bp.route("/order/<int:order_id>/incident", methods=["POST"])
@login_required
def incident_order(order_id):
    return _order_action(order_id, "incident")


@admin_bp.route("/order/<int:order_id>/slip")
@login_required
def view_slip(order_id):
    order = _scoped_order(order_id)
    path = order.get("slip_path")
    if not path or not path.startswith(f"orders/{order_id}/") or ".." in path:
        abort(404)
    signed = get_supabase().storage.from_("slips").create_signed_url(path, 60)
    location = signed.get("signedURL") or signed.get("signedUrl")
    if not location:
        abort(503)
    response = redirect(location)
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _money(value):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or number > 100000 or number != number.quantize(Decimal("0.01")):
            raise ValueError
        return float(number)
    except (InvalidOperation, ValueError):
        raise ValueError("ราคาต้องอยู่ระหว่าง 0 ถึง 100,000 บาท และมีทศนิยมไม่เกิน 2 ตำแหน่ง") from None


def _integer(value, minimum, maximum, label):
    try:
        result = int(str(value))
    except (ValueError, TypeError):
        raise ValueError(f"{label}ต้องเป็นจำนวนเต็ม") from None
    if result < minimum or result > maximum:
        raise ValueError(f"{label}ต้องอยู่ระหว่าง {minimum}–{maximum}")
    return result


def _text(name, maximum, required=False, default=""):
    value = request.form.get(name, default).strip()
    if (required and not value) or len(value) > maximum:
        raise ValueError(f"ข้อมูล {name} ไม่ถูกต้อง (สูงสุด {maximum} ตัวอักษร)")
    return value


def _menu_payload():
    image_url = _text("image_url", 2048)
    if image_url:
        parsed = urlsplit(image_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("รูปเมนูต้องเป็นลิงก์ HTTPS")
    raw_options = request.form.get("options", "[]").strip() or "[]"
    if len(raw_options) > 12000:
        raise ValueError("ตัวเลือกเมนูยาวเกินไป")
    try:
        options = json.loads(raw_options)
    except (TypeError, ValueError):
        raise ValueError("รูปแบบตัวเลือกเมนูไม่ถูกต้อง") from None
    if not isinstance(options, list) or len(options) > 30:
        raise ValueError("เพิ่มตัวเลือกได้ไม่เกิน 30 รายการ")
    clean_options, seen = [], set()
    for option in options:
        if not isinstance(option, dict):
            raise ValueError("รูปแบบตัวเลือกเมนูไม่ถูกต้อง")
        option_id = str(option.get("id", "")).strip()
        name = str(option.get("name", "")).strip()
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", option_id) or option_id in seen or not name or len(name) > 100:
            raise ValueError("รหัสตัวเลือกต้องไม่ซ้ำ และทุกตัวเลือกต้องมีชื่อ")
        seen.add(option_id)
        clean_options.append({"id": option_id, "name": name, "price": _money(option.get("price", 0))})
    return {"name": _text("name", 150, required=True), "price": _money(request.form.get("price", "")),
            "category": _text("category", 80, default="อาหาร") or "อาหาร",
            "description": _text("description", 1000), "image_url": image_url or None,
            "options": clean_options,
            "sort_order": _integer(request.form.get("sort_order", "0"), 0, 10000, "ลำดับเมนู")}


@admin_bp.route("/menu")
@role_required("branch_admin")
def menu_manage():
    branch = _selected_branch()
    items = get_supabase().table("menu_items").select("*").eq("branch_id", branch["id"]) \
        .order("sort_order").order("category").order("name").execute().data or []
    return render_template("menu_manage.html", items=items, branch=branch, branch_id=branch["id"], branches=accessible_branches())


@admin_bp.route("/menu/add", methods=["POST"])
@role_required("branch_admin")
def menu_add():
    branch = require_branch(request.form.get("branch_id"))
    try:
        payload = _menu_payload()
    except ValueError as error:
        flash(str(error))
        return redirect(url_for("admin.menu_manage", branch_id=branch["id"]))
    payload["branch_id"] = branch["id"]
    get_supabase().table("menu_items").insert(payload).execute()
    log_action("menu_add", entity=payload["name"], branch_id=branch["id"])
    flash("เพิ่มเมนูแล้ว")
    return redirect(url_for("admin.menu_manage", branch_id=branch["id"]))


def _scoped_item(item_id):
    rows = get_supabase().table("menu_items").select("*").eq("id", valid_uuid(item_id)).limit(1).execute().data
    if not rows:
        abort(404)
    require_branch(rows[0]["branch_id"])
    return rows[0]


@admin_bp.route("/menu/<item_id>/edit", methods=["POST"])
@role_required("branch_admin")
def menu_edit(item_id):
    item = _scoped_item(item_id)
    try:
        payload = _menu_payload()
    except ValueError as error:
        flash(str(error))
        return redirect(url_for("admin.menu_manage", branch_id=item["branch_id"]))
    get_supabase().table("menu_items").update(payload).eq("id", item["id"]).eq("branch_id", item["branch_id"]).execute()
    log_action("menu_edit", entity=f"menu:{item['id']}", branch_id=item["branch_id"])
    flash("บันทึกเมนูแล้ว")
    return redirect(url_for("admin.menu_manage", branch_id=item["branch_id"]))


@admin_bp.route("/menu/<item_id>/toggle", methods=["POST"])
@role_required("branch_admin")
def menu_toggle(item_id):
    item = _scoped_item(item_id)
    available = not item["is_available"]
    get_supabase().table("menu_items").update({"is_available": available}).eq("id", item["id"]).eq("branch_id", item["branch_id"]).execute()
    log_action("menu_toggle", entity=f"menu:{item['id']}", details={"is_available": available}, branch_id=item["branch_id"])
    return redirect(url_for("admin.menu_manage", branch_id=item["branch_id"]))


def _settings_payload(branch):
    timezone = _text("timezone", 80, default=branch.get("timezone", "Asia/Bangkok"))
    try:
        ZoneInfo(timezone)
    except (ValueError, ZoneInfoNotFoundError):
        raise ValueError("เขตเวลาไม่ถูกต้อง") from None
    opening, closing = _text("opening_time", 8), _text("closing_time", 8)
    if bool(opening) != bool(closing):
        raise ValueError("กรุณาระบุเวลาเปิดและปิดให้ครบ")
    if opening:
        try:
            open_time, close_time = time.fromisoformat(opening), time.fromisoformat(closing)
            if open_time.tzinfo is not None or close_time.tzinfo is not None:
                raise ValueError
            opening, closing = open_time.isoformat(), close_time.isoformat()
        except ValueError:
            raise ValueError("เวลาเปิดหรือปิดไม่ถูกต้อง") from None
    promptpay_id = _text("promptpay_id", 25).replace("-", "").replace(" ", "")
    promptpay_name = _text("promptpay_name", 150)
    if promptpay_id and not re.fullmatch(r"(?:0[0-9]{9}|[0-9]{13}|[0-9]{15})", promptpay_id):
        raise ValueError("พร้อมเพย์ต้องเป็นเบอร์โทร 10 หลัก เลขประจำตัว 13 หลัก หรือ e-Wallet 15 หลัก")
    if bool(promptpay_id) != bool(promptpay_name):
        raise ValueError("กรุณาระบุหมายเลขพร้อมเพย์และชื่อผู้รับเงินให้ครบ")
    data = {"name": _text("name", 150, required=True), "address": _text("address", 500),
            "campus": _text("campus", 150), "pickup_point": _text("pickup_point", 250),
            "timezone": timezone, "opening_time": opening or "00:00:00", "closing_time": closing or "00:00:00",
            "promptpay_id": promptpay_id or None, "promptpay_name": promptpay_name,
            "is_accepting_orders": request.form.get("is_accepting_orders") in ("1", "true", "on"),
            "allow_cash_before_payment": request.form.get("allow_cash_before_payment") in ("1", "true", "on")}
    for name, low, high, default, label in (
        ("prep_minutes", 1, 180, 10, "เวลาเตรียมอาหาร"), ("kitchen_capacity", 1, 100, 1, "จำนวนงานพร้อมกัน"),
        ("slot_minutes", 5, 60, 15, "ช่วงเวลารับอาหาร"), ("slot_capacity", 0, 500, 10, "จำนวนออเดอร์ต่อช่วง"),
        ("preorder_days", 0, 30, 3, "จำนวนวันสั่งล่วงหน้า"),
    ):
        data[name] = _integer(request.form.get(name, str(branch.get(name, default))), low, high, label)
    if data["slot_minutes"] not in (5, 10, 15, 20, 30, 60):
        raise ValueError("ช่วงเวลารับอาหารต้องเป็น 5, 10, 15, 20, 30 หรือ 60 นาที")
    return data


@admin_bp.route("/branches/<branch_id>/settings", methods=["GET", "POST"])
@role_required("branch_admin")
def branch_settings(branch_id):
    branch = require_branch(branch_id)
    if request.method == "POST":
        try:
            payload = _settings_payload(branch)
        except ValueError as error:
            flash(str(error))
            return render_template("branch_settings.html", branch=branch, branches=accessible_branches()), 400
        get_supabase().table("branches").update(payload).eq("id", branch["id"]).execute()
        # Record which fields changed without duplicating a receiving account in logs.
        fields = [key for key, value in payload.items() if value != branch.get(key)]
        log_action("branch_settings", entity=f"branch:{branch['id']}", details={"changed_fields": fields}, branch_id=branch["id"])
        flash("บันทึกการตั้งค่าร้านแล้ว")
        return redirect(url_for("admin.branch_settings", branch_id=branch["id"]))
    return render_template("branch_settings.html", branch=branch, branches=accessible_branches())


@admin_bp.route("/branches/<branch_id>/toggle-orders", methods=["POST"])
@login_required
def toggle_orders(branch_id):
    branch = require_branch(branch_id)
    if not branch.get("is_active", True):
        flash("ร้านนี้ปิดใช้งานอยู่ กรุณาติดต่อผู้ดูแลองค์กรเพื่อเปิดใช้งานร้านก่อนรับออเดอร์")
        return redirect(url_for("admin.kitchen", branch_id=branch["id"]))
    accepting = not branch.get("is_accepting_orders", True)
    get_supabase().table("branches").update({"is_accepting_orders": accepting}).eq("id", branch["id"]).execute()
    log_action("toggle_orders", entity=f"branch:{branch['id']}", details={"is_accepting_orders": accepting}, branch_id=branch["id"])
    flash("เปิดรับออเดอร์แล้ว" if accepting else "พักรับออเดอร์แล้ว ออเดอร์เดิมยังดำเนินการต่อได้")
    return redirect(url_for("admin.kitchen", branch_id=branch["id"]))


def _walk_in_items(branch_id):
    return get_supabase().table("menu_items").select("*").eq("branch_id", branch_id) \
        .eq("is_available", True).order("sort_order").order("name").execute().data or []


def _walk_in_attempt(branch, items):
    """Keep the shown prices stable across retries, without trusting hidden inputs."""
    staff_id = current_staff()["id"]
    now = timestamp()
    attempts = {key: attempt for key, attempt in session.get("walk_in_attempts", {}).items()
                if attempt.get("staff_id") == staff_id and attempt.get("expires_at", 0) > now}
    attempts = dict(sorted(attempts.items(), key=lambda entry: entry[1]["expires_at"])[-7:])
    key = str(uuid4())
    attempts[key] = {
        "branch_id": branch["id"], "staff_id": staff_id,
        "expires_at": min(now + 28800, session.get("staff_auth_until", now + 28800)),
        "prices": {str(item["id"]): {
            "base": str(item["price"]),
            "options": {str(option["id"]): str(option["price"]) for option in (item.get("options") or [])},
        } for item in items},
    }
    session["walk_in_attempts"] = attempts
    return key


@admin_bp.route("/kitchen/<branch_id>/walk-in", methods=["GET", "POST"])
@login_required
def walk_in(branch_id):
    from app.services.orders import rpc_result, stable_access_token, token_hash
    branch = require_branch(branch_id)
    if not branch.get("is_active", True):
        flash("ร้านนี้ปิดใช้งานอยู่ จึงยังรับออเดอร์ใหม่ไม่ได้")
        return redirect(url_for("admin.kitchen", branch_id=branch["id"]))
    items = _walk_in_items(branch["id"])

    def form_response(message=None, status=200):
        if message:
            flash(message)
        current_items = _walk_in_items(branch["id"]) if message else items
        return render_template("walk_in.html", branch=branch, items=current_items,
                               idempotency_key=_walk_in_attempt(branch, current_items)), status

    if request.method == "POST":
        try:
            raw_key = request.form.get("idempotency_key", "")
            try:
                idempotency_key = str(UUID(raw_key))
            except (ValueError, TypeError):
                raise ValueError("แบบฟอร์มออเดอร์ไม่ถูกต้อง กรุณาตรวจรายการแล้วกดยืนยันอีกครั้ง") from None
            attempt = session.get("walk_in_attempts", {}).get(idempotency_key)
            if (not attempt or attempt.get("branch_id") != branch["id"]
                    or attempt.get("staff_id") != current_staff()["id"]
                    or attempt.get("expires_at", 0) <= timestamp()):
                raise ValueError("แบบฟอร์มนี้หมดอายุ กรุณาตรวจรายการและราคาปัจจุบันแล้วกดยืนยันอีกครั้ง")
            selected = []
            # Build a deterministic request from the submitted quantities. The RPC
            # checks current menu membership/availability for a new order, while an
            # exact replay still succeeds even if a menu is sold out afterwards.
            for field in sorted(request.form):
                if not field.startswith("qty_"):
                    continue
                item_id = str(UUID(field[4:]))
                quantity = _integer(request.form.get(field, "0") or "0", 0, 20, "จำนวนอาหาร")
                if quantity:
                    quoted_item = attempt["prices"].get(item_id)
                    if not quoted_item:
                        raise ValueError("เมนูเปลี่ยนไป กรุณาตรวจรายการปัจจุบันแล้วเลือกอีกครั้ง")
                    option_ids = sorted(request.form.getlist(f"option_ids_{item_id}"))
                    if len(option_ids) > 20 or len(option_ids) != len(set(option_ids)):
                        raise ValueError("เลือกตัวเลือกไม่ซ้ำกันได้สูงสุด 20 รายการต่อเมนู")
                    if any(option_id not in quoted_item["options"] for option_id in option_ids):
                        raise ValueError("ตัวเลือกเมนูเปลี่ยนไป กรุณาเลือกอีกครั้ง")
                    expected_price = Decimal(quoted_item["base"]) + sum(
                        (Decimal(quoted_item["options"][option_id]) for option_id in option_ids), Decimal("0"))
                    selected.append({"menu_item_id": item_id, "quantity": quantity,
                                     "option_ids": option_ids, "note": "",
                                     "expected_unit_price": format(expected_price, ".2f")})
            if not selected:
                raise ValueError("กรุณาเลือกอาหารอย่างน้อย 1 รายการ")
            if len(selected) > 30:
                raise ValueError("หนึ่งออเดอร์มีเมนูได้ไม่เกิน 30 รายการ")
            payment_method = request.form.get("payment_method", "cash")
            if payment_method not in ("cash", "promptpay"):
                raise ValueError("วิธีชำระเงินไม่ถูกต้อง")
            requested_for = request.form.get("requested_for", "").strip()
            if requested_for:
                scheduled = datetime.fromisoformat(requested_for)
                if scheduled.tzinfo is None:
                    scheduled = scheduled.replace(tzinfo=ZoneInfo(branch.get("timezone", "Asia/Bangkok")))
                requested_for = scheduled.isoformat()
            payload = {"p_branch_id": branch["id"], "p_items": selected,
                       "p_student_name": _text("student_name", 100, default="Walk-in") or "Walk-in",
                       "p_room_no": _text("room_no", 40), "p_note": _text("note", 300),
                       "p_payment_method": payment_method, "p_idempotency_key": idempotency_key,
                       "p_token_hash": token_hash(stable_access_token(idempotency_key)),
                       "p_staff_id": current_staff()["id"], "p_requested_for": requested_for or None}
        except (ValueError, ZoneInfoNotFoundError) as error:
            return form_response(str(error) or "ข้อมูลออเดอร์ไม่ถูกต้อง", 400)
        try:
            order = rpc_result(get_supabase().rpc("create_order", payload).execute())
        except Exception as error:
            known = error if isinstance(error, UserError) else database_error(error)
            if not known:
                raise
            message = known.message
            if getattr(error, "message", "") in ("price_changed", "idempotency_conflict"):
                message = "รายการหรือราคาเปลี่ยนไป กรุณาตรวจยอดปัจจุบันแล้วกดยืนยันอีกครั้ง"
            return form_response(message, known.status)
        if payment_method == "promptpay":
            flash(f"รับออเดอร์ {order.get('order_code', '')} แล้ว แสดง QR นี้ให้ลูกค้าชำระและแนบหลักฐาน")
            return redirect(url_for("user.payment_page", order_id=order["id"],
                                    token=stable_access_token(idempotency_key)), code=303)
        flash(f"รับออเดอร์ {order.get('order_code', '')} แล้ว โปรดบันทึกการรับเงินจริงก่อนปิดงาน")
        return redirect(url_for("admin.kitchen", branch_id=branch["id"]))
    return form_response()


@admin_bp.route("/dashboard")
@role_required("branch_admin")
def dashboard():
    from app.services.orders import rpc_result
    branch = _selected_branch()
    today = datetime.now(ZoneInfo(branch.get("timezone", "Asia/Bangkok"))).date()
    try:
        selected_date = date.fromisoformat(request.args.get("date", today.isoformat()))
    except ValueError:
        abort(400)
    metrics = rpc_result(get_supabase().rpc("branch_dashboard", {"p_branch_id": branch["id"],
                         "p_staff_id": current_staff()["id"], "p_date": selected_date.isoformat()}).execute())
    return render_template("dashboard.html", branch=branch, branches=accessible_branches(),
                           metrics=metrics, top_items=metrics.get("top_items", []), selected_date=selected_date.isoformat(),
                           total_today=metrics.get("orders_total", 0), completed_today=metrics.get("orders_completed", 0),
                           cancelled_today=metrics.get("orders_cancelled", 0), active_now=metrics.get("orders_active", 0),
                           avg_prep_minutes=metrics.get("prep_minutes_p50", 0), revenue_today=metrics.get("paid_total", 0))


@admin_bp.route("/branches/<branch_id>/qr")
@login_required
def branch_qr(branch_id):
    from app.utils import make_qr_base64
    branch = require_branch(branch_id)
    base = current_app.config.get("PUBLIC_BASE_URL", "").rstrip("/")
    path = url_for("user.index", branch_id=branch["id"])
    menu_url = base + path if base else url_for("user.index", branch_id=branch["id"], _external=True)
    return render_template("branch_qr.html", branch=branch, menu_url=menu_url, qr_b64=make_qr_base64(menu_url))


# ============================================================================
# SUPER ADMIN ROUTES (บทบาทสูงสุด: จัดการผู้ใช้, รหัสผ่าน, สาขา, องค์กร)
# ============================================================================

@admin_bp.route("/super")
@role_required("super_admin")
def super_dashboard():
    from app.services.management import get_system_metrics
    db = get_supabase()
    metrics = get_system_metrics(db)
    branches = db.table("branches").select("*").order("name").execute().data or []
    orgs = db.table("organizations").select("*").order("name").execute().data or []
    org_map = {o["id"]: o.get("name", o["id"]) for o in orgs}
    return render_template("super_dashboard.html", metrics=metrics, branches=branches,
                           org_map=org_map, staff=current_staff())


@admin_bp.route("/super/branches")
@role_required("super_admin")
def super_branches():
    db = get_supabase()
    branches = db.table("branches").select("*").order("name").execute().data or []
    orgs = db.table("organizations").select("*").order("name").execute().data or []
    org_map = {o["id"]: o.get("name", o["id"]) for o in orgs}
    return render_template("super_branches.html", branches=branches, organizations=orgs,
                           org_map=org_map, staff=current_staff())


@admin_bp.route("/super/branches/create", methods=["POST"])
@role_required("super_admin")
def super_create_branch():
    from app.services.management import create_branch as mgmt_create_branch
    db = get_supabase()
    try:
        org_id = request.form.get("organization_id")
        name = request.form.get("name", "")
        campus = request.form.get("campus", "")
        pickup_point = request.form.get("pickup_point", "")
        timezone = request.form.get("timezone", "Asia/Bangkok")
        branch = mgmt_create_branch(db, organization_id=org_id, name=name,
                                    campus=campus, pickup_point=pickup_point, timezone=timezone)
        log_action("super_create_branch", entity=f"branch:{branch['id']}",
                   details={"name": branch["name"], "organization_id": org_id})
        flash(f"เปิดสาขา '{branch['name']}' เรียบร้อยแล้ว")
    except ValueError as error:
        flash(str(error), "error")
    except Exception as error:
        flash(f"สร้างสาขาไม่สำเร็จ: {error}", "error")
    return redirect(url_for("admin.super_branches"))


@admin_bp.route("/super/branches/<branch_id>/toggle-active", methods=["POST"])
@role_required("super_admin")
def super_toggle_branch_active(branch_id):
    from app.services.management import toggle_branch_active as mgmt_toggle_branch_active
    db = get_supabase()
    try:
        is_active, branch_name = mgmt_toggle_branch_active(db, branch_id)
        log_action("super_toggle_branch_active", entity=f"branch:{branch_id}", details={"is_active": is_active})
        flash(f"{'เปิดใช้งาน' if is_active else 'ปิดใช้งาน'}สาขา '{branch_name}' แล้ว")
    except Exception as error:
        flash(str(error), "error")
    return redirect(request.referrer or url_for("admin.super_branches"))


@admin_bp.route("/super/branches/<branch_id>/toggle-orders", methods=["POST"])
@role_required("super_admin")
def super_toggle_branch_orders(branch_id):
    from app.services.management import toggle_branch_orders as mgmt_toggle_branch_orders
    db = get_supabase()
    try:
        accepting, branch_name = mgmt_toggle_branch_orders(db, branch_id)
        log_action("super_toggle_branch_orders", entity=f"branch:{branch_id}", details={"is_accepting_orders": accepting})
        flash(f"{'เปิดรับออเดอร์' if accepting else 'พักรับออเดอร์'}ของสาขา '{branch_name}' แล้ว")
    except Exception as error:
        flash(str(error), "error")
    return redirect(request.referrer or url_for("admin.super_branches"))


@admin_bp.route("/super/organizations")
@role_required("super_admin")
def super_organizations():
    db = get_supabase()
    orgs = db.table("organizations").select("*").order("name").execute().data or []
    branches = db.table("branches").select("id,organization_id").execute().data or []
    staff = db.table("staff").select("id,organization_id").execute().data or []
    
    branch_counts = {}
    for b in branches:
        oid = b.get("organization_id")
        if oid:
            branch_counts[oid] = branch_counts.get(oid, 0) + 1

    staff_counts = {}
    for s in staff:
        oid = s.get("organization_id")
        if oid:
            staff_counts[oid] = staff_counts.get(oid, 0) + 1

    return render_template("super_organizations.html", organizations=orgs,
                           branch_counts=branch_counts, staff_counts=staff_counts, staff=current_staff())


@admin_bp.route("/super/organizations/create", methods=["POST"])
@role_required("super_admin")
def super_create_organization():
    from app.services.management import create_organization as mgmt_create_organization
    db = get_supabase()
    name = request.form.get("name", "")
    try:
        org = mgmt_create_organization(db, name=name)
        log_action("super_create_org", entity=f"org:{org['id']}", details={"name": org["name"]})
        flash(f"สร้างองค์กร '{org['name']}' เรียบร้อยแล้ว")
    except ValueError as error:
        flash(str(error), "error")
    except Exception as error:
        flash(f"สร้างองค์กรไม่สำเร็จ: {error}", "error")
    return redirect(url_for("admin.super_organizations"))


@admin_bp.route("/super/organizations/<org_id>/edit", methods=["POST"])
@role_required("super_admin")
def super_edit_organization(org_id):
    from app.services.management import update_organization as mgmt_update_organization
    db = get_supabase()
    name = request.form.get("name", "")
    try:
        org = mgmt_update_organization(db, organization_id=org_id, name=name)
        log_action("super_edit_org", entity=f"org:{org_id}", details={"new_name": org["name"]})
        flash(f"แก้ไขชื่อองค์กรเป็น '{org['name']}' เรียบร้อยแล้ว")
    except Exception as error:
        flash(str(error), "error")
    return redirect(url_for("admin.super_organizations"))


@admin_bp.route("/super/staff")
@role_required("super_admin")
def super_staff():
    db = get_supabase()
    staff_list = db.table("staff").select("*").order("created_at", desc=True).execute().data or []
    orgs = db.table("organizations").select("*").order("name").execute().data or []
    branches = db.table("branches").select("*").order("name").execute().data or []
    org_map = {o["id"]: o.get("name", o["id"]) for o in orgs}
    branch_map = {b["id"]: b.get("name", b["id"]) for b in branches}
    return render_template("super_staff.html", staff_list=staff_list, organizations=orgs,
                           branches=branches, org_map=org_map, branch_map=branch_map,
                           current_user_id=current_staff()["id"], staff=current_staff())


@admin_bp.route("/super/staff/create", methods=["POST"])
@role_required("super_admin")
def super_create_staff():
    from app.services.management import create_staff_account
    db = get_supabase()
    email = request.form.get("email", "")
    password = request.form.get("password", "")
    role = request.form.get("role", "staff")
    org_id = request.form.get("organization_id")
    branch_id = request.form.get("branch_id")
    try:
        new_staff = create_staff_account(db, email=email, password=password, role=role,
                                         branch_id=branch_id, organization_id=org_id)
        log_action("super_create_staff", entity=f"staff:{new_staff['id']}",
                   details={"username": new_staff["username"], "role": role, "branch_id": branch_id})
        flash(f"สร้างบัญชีเจ้าหน้าที่ '{email}' (Role: {role}) เรียบร้อยแล้ว")
    except ValueError as error:
        flash(str(error), "error")
    except Exception as error:
        flash(f"สร้างบัญชีไม่สำเร็จ: {error}", "error")
    return redirect(url_for("admin.super_staff"))


@admin_bp.route("/super/staff/<staff_id>/reset-password", methods=["POST"])
@role_required("super_admin")
def super_reset_password(staff_id):
    from app.services.management import reset_staff_password
    db = get_supabase()
    new_password = request.form.get("new_password", "")
    try:
        username = reset_staff_password(db, staff_id, new_password)
        log_action("super_reset_password", entity=f"staff:{staff_id}", details={"username": username})
        flash(f"เปลี่ยนรหัสผ่านสำหรับ '{username}' เรียบร้อยแล้ว")
    except Exception as error:
        flash(str(error), "error")
    return redirect(url_for("admin.super_staff"))


@admin_bp.route("/super/staff/<staff_id>/toggle-active", methods=["POST"])
@role_required("super_admin")
def super_toggle_staff_active(staff_id):
    from app.services.management import toggle_staff_active
    db = get_supabase()
    try:
        is_active, username = toggle_staff_active(db, staff_id, current_staff_id=current_staff()["id"])
        log_action("super_toggle_staff_active", entity=f"staff:{staff_id}", details={"is_active": is_active})
        flash(f"{'เปิดใช้งาน' if is_active else 'ระงับสิทธิ์ใช้งาน'}บัญชี '{username}' แล้ว")
    except Exception as error:
        flash(str(error), "error")
    return redirect(url_for("admin.super_staff"))

