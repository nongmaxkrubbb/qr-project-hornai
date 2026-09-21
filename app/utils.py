import io
import base64
import qrcode
from datetime import datetime, date
from app.database import get_supabase


def next_order_number(branch_id, prefix="Q"):
    """ออกเลขออเดอร์แบบ atomic ผ่านฟังก์ชัน next_order_number() ใน database"""
    supabase = get_supabase()
    res = supabase.rpc("next_order_number", {"p_branch_id": branch_id, "p_date": str(date.today())}).execute()
    n = res.data
    return f"{prefix}{n:03d}"


import time
_cache_avg_prep = {}

def avg_prep_seconds(branch_id):
    """เวลาเตรียมอาหารเฉลี่ยของ 20 ออเดอร์ล่าสุดที่เสร็จแล้ว (waiting -> ready)"""
    now = time.time()
    if branch_id in _cache_avg_prep:
        val, ts = _cache_avg_prep[branch_id]
        if now - ts < 60:  # cache for 60 seconds
            return val

    supabase = get_supabase()
    res = supabase.table("orders").select("created_at, ready_at") \
        .eq("branch_id", branch_id).not_.is_("ready_at", "null") \
        .order("ready_at", desc=True).limit(20).execute()
    
    rows = res.data
    if not rows:
        return 600  # ค่าเดาเริ่มต้น: 10 นาที
        
    total, n = 0, 0
    for row in rows:
        try:
            created_at = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
            ready_at = datetime.fromisoformat(row["ready_at"].replace("Z", "+00:00"))
            diff = (ready_at - created_at).total_seconds()
            if diff > 0:
                total += diff
                n += 1
        except Exception:
            pass
            
    avg = int(total / n) if n else 600
    _cache_avg_prep[branch_id] = (avg, now)
    return avg


def orders_ahead(order):
    """จำนวนออเดอร์ที่ยังไม่เสร็จและมาก่อนออเดอร์นี้ (ใช้บอกตำแหน่งคิว)"""
    supabase = get_supabase()
    res = supabase.table("orders").select("id", count="exact") \
        .eq("branch_id", order["branch_id"]) \
        .in_("status", ["waiting", "preparing"]) \
        .lt("id", order["id"]).limit(1).execute()
    
    return res.count if res.count is not None else 0


def make_qr_base64(url):
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


import promptpay

def generate_promptpay_qr_base64(promptpay_id, amount):
    """สร้าง QR Code พร้อมเพย์แบบระบุจำนวนเงิน แล้วคืนค่าเป็น Base64"""
    payload = promptpay.qrcode.generate_payload(promptpay_id, amount)
    img = qrcode.make(payload)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def iso(dt):
    """คืนค่า string (เพราะ Supabase-py คืนเป็น string อยู่แล้ว)"""
    if dt is None:
        return None
    return dt.isoformat(timespec="seconds") if isinstance(dt, datetime) else str(dt)
