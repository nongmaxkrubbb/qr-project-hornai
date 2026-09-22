import re
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.services.auth import ROLE_RANK, valid_uuid


def validate_scope(db, role, branch_id=None, organization_id=None):
    """Validate role scope to ensure safe relationships between organization and branch."""
    if role not in ROLE_RANK:
        raise ValueError("สิทธิ์บทบาทไม่ถูกต้อง")

    branch_id = valid_uuid(branch_id) if branch_id else None
    organization_id = valid_uuid(organization_id) if organization_id else None

    if role == "super_admin":
        return None, None

    if role in {"staff", "branch_admin"} and not branch_id:
        raise ValueError("พนักงาน (staff) และผู้จัดการสาขา (branch_admin) ต้องระบุสาขา")

    if branch_id:
        rows = db.table("branches").select("id,organization_id,is_active").eq("id", branch_id).limit(1).execute().data
        if not rows:
            raise ValueError("ไม่พบสาขาที่ระบุ")
        actual_org = rows[0]["organization_id"]
        if organization_id and str(actual_org) != str(organization_id):
            raise ValueError("สาขาไม่ได้อยู่ในองค์กรที่ระบุ")
        organization_id = actual_org

    if role == "org_admin" and not organization_id:
        raise ValueError("ผู้ดูแลองค์กร (org_admin) ต้องระบุองค์กร")

    if organization_id:
        rows = db.table("organizations").select("id").eq("id", organization_id).limit(1).execute().data
        if not rows:
            raise ValueError("ไม่พบองค์กรที่ระบุ")

    return branch_id, organization_id


def create_organization(db, *, name):
    name = name.strip()
    if not name or len(name) > 150 or any(ord(character) < 32 for character in name):
        raise ValueError("ชื่อองค์กรต้องมี 1–150 ตัวอักษรและไม่มีอักขระควบคุม")
    existing = db.table("organizations").select("id,name").eq("name", name).limit(1).execute().data
    if existing:
        raise ValueError(f"มีองค์กรชื่อ '{name}' อยู่แล้ว")
    result = db.table("organizations").insert({"name": name}).execute()
    if not result.data:
        raise RuntimeError("ไม่สามารถบันทึกองค์กรได้")
    return result.data[0]


def update_organization(db, *, organization_id, name):
    org_id = valid_uuid(organization_id)
    if not org_id:
        raise ValueError("รหัสองค์กรไม่ถูกต้อง")
    name = name.strip()
    if not name or len(name) > 150 or any(ord(character) < 32 for character in name):
        raise ValueError("ชื่อองค์กรต้องมี 1–150 ตัวอักษรและไม่มีอักขระควบคุม")
    result = db.table("organizations").update({"name": name}).eq("id", org_id).execute()
    if not result.data:
        raise ValueError("ไม่พบองค์กรที่ต้องการแก้ไข")
    return result.data[0]


def create_branch(db, *, organization_id, name, campus="", pickup_point="", timezone="Asia/Bangkok"):
    org_id = valid_uuid(organization_id)
    if not org_id:
        raise ValueError("รหัสองค์กรไม่ถูกต้อง")
    try:
        ZoneInfo(timezone)
    except (ValueError, ZoneInfoNotFoundError):
        raise ValueError("เขตเวลาไม่ถูกต้อง")

    name, campus, pickup_point = name.strip(), campus.strip(), pickup_point.strip()
    if not name or len(name) > 150 or len(campus) > 150 or len(pickup_point) > 250:
        raise ValueError("ชื่อร้าน/มหาวิทยาลัย/จุดรับอาหารไม่ถูกต้อง (ความยาวเกินกำหนดหรือว่างเปล่า)")

    if not db.table("organizations").select("id").eq("id", org_id).limit(1).execute().data:
        raise ValueError("ไม่พบองค์กรที่ระบุ")

    result = db.table("branches").insert({
        "organization_id": org_id,
        "name": name,
        "campus": campus,
        "pickup_point": pickup_point,
        "timezone": timezone,
        "is_active": True,
        "is_accepting_orders": False,
    }).execute()
    if not result.data:
        raise RuntimeError("ไม่สามารถสร้างสาขาได้")
    return result.data[0]


def toggle_branch_active(db, branch_id):
    b_id = valid_uuid(branch_id)
    if not b_id:
        raise ValueError("รหัสสาขาไม่ถูกต้อง")
    rows = db.table("branches").select("id,is_active,name").eq("id", b_id).limit(1).execute().data
    if not rows:
        raise ValueError("ไม่พบสาขา")
    new_active = not rows[0].get("is_active", True)
    db.table("branches").update({"is_active": new_active}).eq("id", b_id).execute()
    return new_active, rows[0]["name"]


def toggle_branch_orders(db, branch_id):
    b_id = valid_uuid(branch_id)
    if not b_id:
        raise ValueError("รหัสสาขาไม่ถูกต้อง")
    rows = db.table("branches").select("id,is_accepting_orders,is_active,name").eq("id", b_id).limit(1).execute().data
    if not rows:
        raise ValueError("ไม่พบสาขา")
    if not rows[0].get("is_active", True):
        raise ValueError("สาขานี้ปิดใช้งานอยู่ กรุณาเปิดใช้งานสาขาก่อนเปิดรับออเดอร์")
    new_accepting = not rows[0].get("is_accepting_orders", True)
    db.table("branches").update({"is_accepting_orders": new_accepting}).eq("id", b_id).execute()
    return new_accepting, rows[0]["name"]


def create_staff_account(db, *, email, password, role, branch_id=None, organization_id=None):
    email = email.strip().lower()
    if "@" not in email or len(email) > 254:
        raise ValueError("อีเมลไม่ถูกต้อง")
    if len(password) < 8:
        raise ValueError("รหัสผ่านต้องมีความยาวอย่างน้อย 8 ตัวอักษร")

    branch_id, organization_id = validate_scope(db, role, branch_id, organization_id)

    # Check if staff already exists in staff table
    existing = db.table("staff").select("id,username,auth_user_id").eq("username", email).limit(1).execute().data
    if existing and existing[0].get("auth_user_id"):
        raise ValueError(f"มีบัญชีเจ้าหน้าที่อีเมล '{email}' ในระบบแล้ว")

    # Create user in Supabase Auth via auth.admin
    auth_user_id = None
    try:
        auth_admin = getattr(db.auth, "admin", None)
        if auth_admin:
            auth_res = auth_admin.create_user({
                "email": email,
                "password": password,
                "email_confirm": True,
            })
            auth_user_id = str(auth_res.user.id)
    except Exception as err:
        error_msg = str(err)
        if "already registered" in error_msg.lower() or "already exists" in error_msg.lower():
            raise ValueError(f"อีเมล '{email}' มีอยู่ในระบบยืนยันตัวตนแล้ว กรุณาใช้อีเมลอื่น หรือรีเซ็ตรหัสผ่าน")
        raise ValueError(f"ไม่สามารถสร้างบัญชียืนยันตัวตนได้: {error_msg}")

    staff_data = {
        "auth_user_id": auth_user_id,
        "username": email,
        "role": role,
        "branch_id": branch_id,
        "organization_id": organization_id,
        "is_active": True,
    }

    if existing and not existing[0].get("auth_user_id"):
        result = db.table("staff").update(staff_data).eq("id", existing[0]["id"]).execute()
        staff_row = result.data[0] if result.data else None
    else:
        result = db.table("staff").insert(staff_data).execute()
        staff_row = result.data[0] if result.data else None

    if not staff_row:
        raise RuntimeError("ไม่สามารถบันทึกข้อมูลเจ้าหน้าที่ได้")
    return staff_row


def reset_staff_password(db, staff_id, new_password):
    s_id = valid_uuid(staff_id)
    if not s_id:
        raise ValueError("รหัสเจ้าหน้าที่ไม่ถูกต้อง")
    if len(new_password) < 8:
        raise ValueError("รหัสผ่านใหม่ต้องมีความยาวอย่างน้อย 8 ตัวอักษร")

    rows = db.table("staff").select("id,username,auth_user_id").eq("id", s_id).limit(1).execute().data
    if not rows:
        raise ValueError("ไม่พบเจ้าหน้าที่ที่ระบุ")
    staff = rows[0]
    auth_user_id = staff.get("auth_user_id")
    if not auth_user_id:
        raise ValueError("บัญชีนี้ยังไม่ได้ผูกกับระบบยืนยันตัวตน ไม่สามารถรีเซ็ตรหัสผ่านได้")

    auth_admin = getattr(db.auth, "admin", None)
    if auth_admin:
        auth_admin.update_user_by_id(auth_user_id, {"password": new_password})
    return staff["username"]


def toggle_staff_active(db, staff_id, current_staff_id=None):
    s_id = valid_uuid(staff_id)
    if not s_id:
        raise ValueError("รหัสเจ้าหน้าที่ไม่ถูกต้อง")
    if current_staff_id and str(s_id) == str(current_staff_id):
        raise ValueError("ไม่สามารถระงับสิทธิ์บัญชีของตัวเองได้")

    rows = db.table("staff").select("id,username,is_active,role").eq("id", s_id).limit(1).execute().data
    if not rows:
        raise ValueError("ไม่พบเจ้าหน้าที่ที่ระบุ")
    new_active = not rows[0].get("is_active", True)
    db.table("staff").update({"is_active": new_active}).eq("id", s_id).execute()
    return new_active, rows[0]["username"]


def update_staff_role(db, staff_id, role, branch_id=None, organization_id=None, current_staff_id=None):
    s_id = valid_uuid(staff_id)
    if not s_id:
        raise ValueError("รหัสเจ้าหน้าที่ไม่ถูกต้อง")
    if current_staff_id and str(s_id) == str(current_staff_id) and role != "super_admin":
        raise ValueError("ไม่สามารถลดสิทธิ์บัญชี super_admin ของตัวเองได้")

    branch_id, organization_id = validate_scope(db, role, branch_id, organization_id)
    payload = {
        "role": role,
        "branch_id": branch_id,
        "organization_id": organization_id,
    }
    result = db.table("staff").update(payload).eq("id", s_id).execute()
    if not result.data:
        raise ValueError("ไม่สามารถปรับปรุงข้อมูลเจ้าหน้าที่ได้")
    return result.data[0]


def get_system_metrics(db):
    """Aggregate high-level metrics for super admin dashboard."""
    orgs = db.table("organizations").select("id").execute().data or []
    branches = db.table("branches").select("id,is_active,is_accepting_orders").execute().data or []
    staff = db.table("staff").select("id,role,is_active").execute().data or []
    
    active_branches = sum(1 for b in branches if b.get("is_active"))
    accepting_branches = sum(1 for b in branches if b.get("is_active") and b.get("is_accepting_orders"))
    
    role_counts = {"super_admin": 0, "org_admin": 0, "branch_admin": 0, "staff": 0}
    for s in staff:
        r = s.get("role", "staff")
        if r in role_counts:
            role_counts[r] += 1
            
    orders_res = db.table("orders").select("id,status,payment_status,total_amount").limit(2000).execute().data or []
    total_orders = len(orders_res)
    completed_orders = sum(1 for o in orders_res if o.get("status") == "completed")
    paid_sales = sum(float(o.get("total_amount") or 0) for o in orders_res if o.get("payment_status") == "paid")

    return {
        "total_organizations": len(orgs),
        "total_branches": len(branches),
        "active_branches": active_branches,
        "accepting_branches": accepting_branches,
        "total_staff": len(staff),
        "role_counts": role_counts,
        "total_orders": total_orders,
        "completed_orders": completed_orders,
        "paid_sales": round(paid_sales, 2),
    }
