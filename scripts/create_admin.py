"""
สคริปต์สร้างบัญชีเจ้าหน้าที่คนแรก (super_admin) — รันครั้งเดียวตอน setup ระบบใหม่
(ปรับปรุงสำหรับ Supabase Auth)

การใช้งาน:
    python scripts/create_admin.py --email admin@example.com --branch-id <uuid หรือเว้นว่างได้ถ้าเป็น super_admin>
"""
import argparse
import getpass
import os
import sys
from uuid import UUID

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from supabase import create_client


def validate_scope(supabase, role, branch_id=None, organization_id=None):
    """Validate before creating or modifying an Auth account; never grant an open scope."""
    if role not in {"staff", "branch_admin", "org_admin", "super_admin"}:
        raise ValueError("สิทธิ์ไม่ถูกต้อง")
    branch_id = str(UUID(branch_id)) if branch_id else None
    organization_id = str(UUID(organization_id)) if organization_id else None
    if role in {"staff", "branch_admin"} and not branch_id:
        raise ValueError("staff และ branch_admin ต้องระบุ --branch-id")
    if branch_id:
        rows = supabase.table("branches").select("id,organization_id,is_active").eq("id", branch_id).limit(1).execute().data
        if not rows or not rows[0].get("is_active"):
            raise ValueError("ไม่พบสาขาที่เปิดใช้งาน")
        actual_org = rows[0]["organization_id"]
        if organization_id and str(actual_org) != str(organization_id):
            raise ValueError("สาขาไม่ได้อยู่ในองค์กรที่ระบุ")
        organization_id = actual_org
    if role == "org_admin" and not organization_id:
        raise ValueError("org_admin ต้องระบุ --organization-id")
    if organization_id:
        rows = supabase.table("organizations").select("id").eq("id", organization_id).limit(1).execute().data
        if not rows:
            raise ValueError("ไม่พบองค์กรที่ระบุ")
    return branch_id, organization_id


def main():
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--role", default="super_admin",
                        choices=["staff", "branch_admin", "org_admin", "super_admin"])
    parser.add_argument("--branch-id", default=None)
    parser.add_argument("--organization-id", default=None)
    parser.add_argument("--update-existing", action="store_true", help="ยืนยันการเปลี่ยนรหัสผ่านและสิทธิ์ของบัญชีเดิม")
    args = parser.parse_args()

    password = getpass.getpass("ตั้งรหัสผ่าน: ")
    confirm = getpass.getpass("ยืนยันรหัสผ่านอีกครั้ง: ")
    if password != confirm:
        print("รหัสผ่านไม่ตรงกัน", file=sys.stderr)
        sys.exit(1)
    if len(password) < 12:
        print("รหัสผ่านต้องยาวอย่างน้อย 12 ตัวอักษร", file=sys.stderr)
        sys.exit(1)

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("ไม่พบ SUPABASE_URL หรือ SUPABASE_SERVICE_ROLE_KEY ในไฟล์ .env", file=sys.stderr)
        sys.exit(1)

    supabase = create_client(url, key)

    try:
        branch_id, organization_id = validate_scope(supabase, args.role, args.branch_id, args.organization_id)
        email = args.email.strip().lower()
        if "@" not in email or len(email) > 254:
            raise ValueError("อีเมลไม่ถูกต้อง")
        user_id = None
        # Iterate every page; otherwise an existing user can be missed after launch.
        page = 1
        while True:
            users = supabase.auth.admin.list_users(page=page, per_page=100)
            for user in users:
                if (user.email or "").lower() == email:
                    user_id = user.id
                    break
            if user_id or len(users) < 100:
                break
            page += 1
        existing_profile = supabase.table("staff").select("id,auth_user_id").eq("username", email).limit(1).execute().data
        linked_auth_id = existing_profile[0].get("auth_user_id") if existing_profile else None
        if linked_auth_id and str(linked_auth_id) != str(user_id or ""):
            raise ValueError("มีชื่อบัญชีนี้ในตาราง staff ซึ่งผูกกับ Auth คนละบัญชี กรุณาแก้การเชื่อมบัญชีเดิมก่อนเพื่อป้องกันการเปลี่ยนสิทธิ์ผิดคน")
        if existing_profile and not linked_auth_id and not args.update_existing:
            raise ValueError("พบโปรไฟล์เดิมที่ไม่มีบัญชี Auth ระบุ --update-existing เพื่อเชื่อมบัญชีและกำหนดสิทธิ์ของโปรไฟล์เดิม")
        if user_id:
            if not args.update_existing:
                raise ValueError("บัญชีนี้มีอยู่แล้ว หากต้องการเปลี่ยนรหัสผ่าน/สิทธิ์ ให้ระบุ --update-existing")
            supabase.auth.admin.update_user_by_id(user_id, {"password": password})
                
        # 2. ถ้าไม่มี ค่อยสร้างใหม่
        if not user_id:
            auth_res = supabase.auth.admin.create_user({
                "email": email,
                "password": password,
                "email_confirm": True
            })
            user_id = auth_res.user.id

        # บันทึกลงตาราง staff
        staff_data = {
            "auth_user_id": user_id,
            "username": email,
            "role": args.role,
            "branch_id": branch_id,
            "organization_id": organization_id,
            "password_hash": None, 
            "is_active": True
        }
        
        if existing_profile and not linked_auth_id:
            # Keep legacy staff IDs so historical audit references remain intact.
            result = supabase.table("staff").update(staff_data).eq("id", existing_profile[0]["id"]) \
                .is_("auth_user_id", "null").execute()
            if not result.data:
                raise ValueError("โปรไฟล์ถูกเปลี่ยนโดยผู้ดูแลอื่น กรุณาตรวจสอบบัญชีก่อนลองใหม่")
        else:
            supabase.table("staff").upsert(staff_data, on_conflict="auth_user_id").execute()
        
        print(f"✅ สร้าง/อัปเดตผู้ใช้ '{args.email}' (role={args.role}) เรียบร้อยแล้ว! สามารถนำไปล็อกอินได้เลย")
    except ValueError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
    except Exception:
        print("บันทึกบัญชีไม่สำเร็จ ตรวจสอบการเชื่อมต่อและ migration หาก Auth ถูกสร้างแล้ว ให้แก้สาเหตุและรันด้วย --update-existing", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
