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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--role", default="super_admin",
                        choices=["staff", "branch_admin", "org_admin", "super_admin"])
    parser.add_argument("--branch-id", default=None)
    parser.add_argument("--organization-id", default=None)
    args = parser.parse_args()

    password = getpass.getpass("ตั้งรหัสผ่าน: ")
    confirm = getpass.getpass("ยืนยันรหัสผ่านอีกครั้ง: ")
    if password != confirm:
        print("รหัสผ่านไม่ตรงกัน", file=sys.stderr)
        sys.exit(1)
    if len(password) < 6:
        print("รหัสผ่านควรยาวอย่างน้อย 6 ตัวอักษรสำหรับ Supabase Auth", file=sys.stderr)
        sys.exit(1)

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("ไม่พบ SUPABASE_URL หรือ SUPABASE_SERVICE_ROLE_KEY ในไฟล์ .env", file=sys.stderr)
        sys.exit(1)

    supabase = create_client(url, key)

    try:
        user_id = None
        # 1. ลองดึงข้อมูลผู้ใช้ทั้งหมดมาหาว่ามีอีเมลนี้อยู่แล้วหรือไม่
        users_res = supabase.auth.admin.list_users()
        for u in users_res:
            if u.email == args.email:
                user_id = u.id
                print(f"พบผู้ใช้ {args.email} ในระบบ Auth แล้ว (ID: {user_id}), จะทำการอัปเดตรหัสผ่านและผูกสิทธิ์ให้...")
                # อัปเดตรหัสผ่าน
                supabase.auth.admin.update_user_by_id(user_id, {"password": password})
                break
                
        # 2. ถ้าไม่มี ค่อยสร้างใหม่
        if not user_id:
            auth_res = supabase.auth.admin.create_user({
                "email": args.email,
                "password": password,
                "email_confirm": True
            })
            user_id = auth_res.user.id

        # บันทึกลงตาราง staff
        staff_data = {
            "auth_user_id": user_id,
            "username": args.email,
            "role": args.role,
            "branch_id": args.branch_id,
            "organization_id": args.organization_id,
            "password_hash": None, 
            "is_active": True
        }
        
        # upsert ด้วย username
        supabase.table("staff").upsert(staff_data, on_conflict="username").execute()
        
        print(f"✅ สร้าง/อัปเดตผู้ใช้ '{args.email}' (role={args.role}) เรียบร้อยแล้ว! สามารถนำไปล็อกอินได้เลย")
    except Exception as e:
        print(f"เกิดข้อผิดพลาดในการบันทึกข้อมูล: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()