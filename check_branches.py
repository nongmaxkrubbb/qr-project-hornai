import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

if url and key:
    supabase = create_client(url, key)
    res = supabase.table("branches").select("*").execute()
    print("Branches:", res.data)
else:
    print("Missing credentials")
