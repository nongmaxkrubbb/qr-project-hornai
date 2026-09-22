"""Create an organization after installing the Supabase schema.

The printed ID is used by create_branch.py and org_admin account setup.
This command does not create sample shops or grant staff access.
"""
import argparse
import os
import sys

from dotenv import load_dotenv
from supabase import create_client


def create_organization(db, *, name):
    name = name.strip()
    if not name or len(name) > 150 or any(ord(character) < 32 for character in name):
        raise ValueError("ชื่อองค์กรต้องมี 1–150 ตัวอักษรและไม่มีอักขระควบคุม")
    existing = db.table("organizations").select("id,name").eq("name", name).limit(1).execute().data
    if existing:
        raise ValueError(f"มีองค์กรชื่อนี้แล้ว: {existing[0]['id']} ใช้รหัสนี้สร้างร้าน หรือเลือกชื่อองค์กรใหม่")
    result = db.table("organizations").insert({"name": name}).execute()
    if not result.data:
        raise RuntimeError("No created organization returned")
    return result.data[0]


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        parser.error("ต้องตั้ง SUPABASE_URL และ SUPABASE_SERVICE_ROLE_KEY")
    try:
        organization = create_organization(create_client(url, key), name=args.name)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:
        print("สร้างองค์กรไม่สำเร็จ โปรดตรวจสอบการเชื่อมต่อและ migration ก่อนลองใหม่", file=sys.stderr)
        return 1
    print(f"สร้างองค์กร {organization['name']} แล้ว: {organization['id']}")
    print(f"สร้างร้านด้วย python scripts/create_branch.py --organization-id {organization['id']} --name 'ชื่อร้าน'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
