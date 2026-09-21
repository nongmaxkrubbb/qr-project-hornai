import os
from supabase import create_client
from dotenv import load_dotenv
load_dotenv()
supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"])
res = supabase.table("orders").select("*").limit(1).execute()
if res.data:
    print("Columns in orders:", list(res.data[0].keys()))
else:
    print("No rows")
