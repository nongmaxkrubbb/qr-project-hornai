"""Create a scoped shop, initially paused, for a known organization.

Run the production-readiness migration first. This command never silently creates
an organization or sets a shop accepting orders before its setup is reviewed.
"""
import argparse
import os
import sys
from uuid import UUID
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from supabase import create_client


def create_branch(db, *, organization_id, name, campus="", pickup_point="", timezone="Asia/Bangkok"):
    organization_id = str(UUID(organization_id))
    ZoneInfo(timezone)
    name, campus, pickup_point = name.strip(), campus.strip(), pickup_point.strip()
    if not name or len(name) > 150 or len(campus) > 150 or len(pickup_point) > 250:
        raise ValueError("ชื่อร้าน/มหาวิทยาลัย/จุดรับอาหารไม่ถูกต้อง")
    if not db.table("organizations").select("id").eq("id", organization_id).limit(1).execute().data:
        raise ValueError("ไม่พบองค์กรที่ระบุ")
    result = db.table("branches").insert({"organization_id": organization_id, "name": name,
               "campus": campus, "pickup_point": pickup_point, "timezone": timezone,
               "is_active": True, "is_accepting_orders": False}).execute()
    if not result.data:
        raise RuntimeError("No created branch returned")
    return result.data[0]


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--organization-id", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--campus", default="")
    parser.add_argument("--pickup-point", default="")
    parser.add_argument("--timezone", default="Asia/Bangkok")
    args = parser.parse_args()
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        parser.error("ต้องตั้ง SUPABASE_URL และ SUPABASE_SERVICE_ROLE_KEY")
    try:
        branch = create_branch(create_client(url, key), organization_id=args.organization_id,
                               name=args.name, campus=args.campus, pickup_point=args.pickup_point,
                               timezone=args.timezone)
    except (ValueError, KeyError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:
        print("สร้างร้านไม่สำเร็จ โปรดตรวจสอบการเชื่อมต่อและ migration ก่อนลองใหม่", file=sys.stderr)
        return 1
    print(f"สร้างร้าน {branch['name']} แล้ว: {branch['id']}")
    print(f"สร้างผู้ดูแลด้วย --role branch_admin --branch-id {branch['id']} จากนั้นตั้งเมนู บัญชีรับเงิน เวลาเปิด และเปิดรับออเดอร์")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
