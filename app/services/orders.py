import base64
import hashlib
import hmac
import math
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID
from zoneinfo import ZoneInfo

from flask import current_app

from app.database import get_supabase
from app.services.errors import UserError, database_error

PUBLIC_BRANCH_FIELDS = (
    "id,name,campus,pickup_point,address,timezone,is_active,is_accepting_orders,"
    "opening_time,closing_time,prep_minutes,kitchen_capacity,promptpay_id,"
    "promptpay_name,allow_cash_before_payment,slot_minutes,slot_capacity,preorder_days"
)


def valid_uuid(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise UserError("รหัสรายการไม่ถูกต้อง", 400)


def bounded_text(value, maximum, label, required=False):
    text = str(value or "").strip()
    if (required and not text) or len(text) > maximum:
        raise UserError(f"กรุณาระบุ{label}ไม่เกิน {maximum} ตัวอักษร")
    return text


def money(value):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or number > Decimal("999999.99"):
            raise ValueError
        return number.quantize(Decimal("0.01"))
    except (ValueError, InvalidOperation):
        raise UserError("ราคาต้องเป็นจำนวนเงินที่ถูกต้องและไม่ติดลบ")


def stable_access_token(idempotency_key):
    key = str(current_app.config["SECRET_KEY"]).encode()
    digest = hmac.new(key, ("order-access:v1:" + valid_uuid(idempotency_key)).encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def token_hash(token):
    return hashlib.sha256(str(token).encode()).hexdigest()


def rpc_result(response):
    data = response.data
    if isinstance(data, list):
        return data[0] if data else {}
    return data or {}


def call_rpc(name, params):
    try:
        return rpc_result(get_supabase().rpc(name, params).execute())
    except Exception as exc:
        error = database_error(exc)
        if error:
            raise error from exc
        raise


def get_branch(branch_id, include_inactive=False):
    branch_id = valid_uuid(branch_id)
    query = get_supabase().table("branches").select(PUBLIC_BRANCH_FIELDS).eq("id", branch_id)
    if not include_inactive:
        query = query.eq("is_active", True)
    response = query.limit(1).execute()
    if not response.data:
        raise UserError("ไม่พบร้านนี้หรือร้านหยุดให้บริการ", 404)
    return response.data[0]


def parse_datetime(value):
    if not value:
        return None
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result


def branch_accepting(branch, now=None):
    if not branch.get("is_active", True) or not branch.get("is_accepting_orders", True):
        return False
    now = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(branch.get("timezone") or "Asia/Bangkok"))
    opening = str(branch.get("opening_time") or "08:00")[:5]
    closing = str(branch.get("closing_time") or "20:00")[:5]
    clock = now.strftime("%H:%M")
    if opening == closing:
        return True
    return opening <= clock < closing if opening < closing else clock >= opening or clock < closing


def estimate_wait(branch, ahead=0, order=None, now=None):
    now = now or datetime.now(timezone.utc)
    if order and order.get("status") in ("ready", "completed", "cancelled"):
        return {"min": 0, "max": 0}
    prep = max(1, int(branch.get("prep_minutes") or 10))
    capacity = max(1, int(branch.get("kitchen_capacity") or 1))
    minutes = prep * (math.floor(max(0, ahead) / capacity) + 1)
    if order and order.get("status") == "preparing" and order.get("started_at"):
        elapsed = (now - parse_datetime(order["started_at"])).total_seconds() / 60
        minutes = max(1, prep - elapsed)
    if order and order.get("requested_for"):
        minutes = max(minutes, (parse_datetime(order["requested_for"]) - now).total_seconds() / 60)
    return {"min": max(1, math.floor(minutes * .8)), "max": max(2, math.ceil(minutes * 1.3))}


def active_ahead(branch_id, order=None, branch=None):
    query = get_supabase().table("orders").select("id", count="exact", head=True).eq("branch_id", branch_id).in_("status", ["waiting", "preparing"])
    horizon = (parse_datetime(order.get("requested_for")) if order else None) or (datetime.now(timezone.utc) + timedelta(minutes=int((branch or {}).get("prep_minutes") or 10)))
    query = query.or_("requested_for.is.null,requested_for.lte." + horizon.isoformat())
    if order:
        query = query.lt("id", order["id"])
    return query.execute().count or 0


def get_order(order_id, token):
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{40,100}", token):
        raise UserError("ไม่พบออเดอร์หรือไม่มีสิทธิ์เข้าถึง", 404)
    response = get_supabase().table("orders").select("*, order_items(*)").eq("id", order_id).eq("token_hash", token_hash(token)).limit(1).execute()
    if not response.data:
        raise UserError("ไม่พบออเดอร์หรือไม่มีสิทธิ์เข้าถึง", 404)
    return response.data[0]


def create_order(**kwargs):
    return call_rpc("create_order", {"p_" + key: value for key, value in kwargs.items()})


def requested_slots(branch, now=None):
    if not branch.get("slot_capacity"):
        return []
    zone = ZoneInfo(branch.get("timezone") or "Asia/Bangkok")
    now = (now or datetime.now(timezone.utc)).astimezone(zone)
    interval = max(5, int(branch.get("slot_minutes") or 15))
    lower = now + timedelta(minutes=max(1, int(branch.get("prep_minutes") or 10)))
    result = []
    for offset in range(min(30, int(branch.get("preorder_days") or 0)) + 1):
        day = (now + timedelta(days=offset)).replace(hour=0, minute=0, second=0, microsecond=0)
        for minute in range(0, 1440, interval):
            value = day + timedelta(minutes=minute)
            if value <= lower or not branch_accepting(branch, value):
                continue
            result.append({"value": value.isoformat(), "iso": value.isoformat(), "label": value.strftime("%d/%m %H:%M")})
    return result[:200]
