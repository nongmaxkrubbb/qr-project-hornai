import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY"))

print("--- Auth Users ---")
try:
    users = supabase.auth.admin.list_users()
    for u in users:
        print(f"Auth ID: {u.id}, Email: {u.email}")
except Exception as e:
    print(f"Error fetching auth users: {e}")

print("\n--- Staff Table ---")
res = supabase.table("staff").select("*").execute()
for s in res.data:
    print(s)
